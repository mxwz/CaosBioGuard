import sys
import os
import logging
import secrets
import hashlib
from datetime import timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, session
from werkzeug.utils import secure_filename
import cv2
import numpy as np
from dotenv import load_dotenv, find_dotenv

# Add parent directory to path to import managers
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from managers import SyncDatabaseManager, ConfigManager, DatabaseLogHandler

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Change this in production

# Initialize managers
# Ensure we are using absolute paths based on the project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The data is located in sideUI/dd and sideUI/face_images
DB_PATH = os.path.join(BASE_DIR, "sideUI", "dd", "face_database.pkl")
SQLITE_PATH = os.path.join(BASE_DIR, "sideUI", "dd", "records.db")
FACE_IMAGES_DIR = os.path.join(BASE_DIR, "sideUI", "face_images")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "web_admin", "uploads")

db_manager = SyncDatabaseManager(database_path=DB_PATH, sqlite_path=SQLITE_PATH)
# Override face_images_dir to be absolute
db_manager.face_images_dir = FACE_IMAGES_DIR
if not os.path.exists(FACE_IMAGES_DIR):
    os.makedirs(FACE_IMAGES_DIR)

# Use default config (root/config.ini) to ensure consistency with db_manager
config_manager = ConfigManager() 
# LS showed config.ini in arcface root AND sideUI/config.ini?
# LS showed:
# arcface/config.ini
# arcface/sideUI/config.ini (Not explicitly shown but sideUI_unified uses config.ini)
# sideUI_unified.py: line 1773: default "config.ini" (relative to script if run from script dir?)
# config_manager uses base_dir of the script file (managers.py).
# managers.py is in arcface root.
# So managers.py will look for config.ini in arcface root.
# But sideUI_unified.py (before my change) used base_dir of itself (sideUI).
# So sideUI_unified.py was using sideUI/config.ini.

# Now sideUI_unified.py imports ConfigManager from managers.py.
# managers.py uses base_dir of managers.py (arcface root).
# So sideUI_unified.py will now use arcface/config.ini!
# This is a change in behavior. I should probably point ConfigManager to sideUI/config.ini.

# But ConfigManager in managers.py takes config_path argument.
# In sideUI_unified.py, it instantiates ConfigManager().
# So it uses default.
# I should change managers.py to accept an absolute path or relative to something specific?
# Or I should change sideUI_unified.py to pass the correct path.

# Let's check sideUI_unified.py instantiation of ConfigManager.
# line 2009: self.config_manager = ConfigManager()
# It uses default.

# So if I want to preserve behavior, I should make sure managers.py uses sideUI/config.ini if called from sideUI_unified?
# Or I should just accept that it uses arcface/config.ini now.
# But arcface/config.ini might be different.
# Let's try to make managers.py use the config relative to the calling script? No, that's messy.
# I should just specify the path.

# Better: Update sideUI_unified.py to pass the path.
# self.config_manager = ConfigManager(os.path.join(os.path.dirname(__file__), "config.ini"))
# This ensures it uses sideUI/config.ini.

# And for database, sideUI_unified.py instantiates SyncDatabaseManager().
# managers.py default is ./dd/face_database.pkl.
# If managers.py is in arcface, and we run sideUI_unified.py (cwd=sideUI), then ./dd is sideUI/dd.
# So database path is fine if CWD is correct.

# But config path in managers.py uses __file__ (managers.py location).
# So it will look in arcface/config.ini.
# I MUST update sideUI_unified.py to pass the config path.

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add Database Log Handler
db_handler = DatabaseLogHandler(db_manager)
db_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(db_handler)

# Initialize Face Analysis Model (Preload)
def load_face_model():
    """Load Face Analysis Model"""
    if hasattr(app, 'face_app') and app.face_app is not None:
        return
        
    logger.info("Preloading Face Analysis Model... This may take a while.")
    try:
        from insightface.app import FaceAnalysis
        # Use global variable for the app
        face_app_instance = FaceAnalysis(providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        face_app_instance.prepare(ctx_id=0, det_size=(640, 640))
        app.face_app = face_app_instance
        logger.info("Face Analysis Model loaded successfully.")
    except Exception as e:
        logger.error(f"Failed to load Face Analysis Model: {e}")
        app.face_app = None

# Only preload in the child process when using reloader (WERKZEUG_RUN_MAIN='true')
# Or if running in production (not __main__)
# This prevents double loading in debug mode
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or __name__ != '__main__':
    load_face_model()
else:
    # In main process of reloader, or if debug=False (no reloader), we skip preload.
    # If debug=False, it will lazy load on first request.
    logger.info("Skipping model preload in main process/reloader parent.")
    app.face_app = None

# --- Auth Setup ---
def hash_password(password, salt):
    """MD5(password + salt)"""
    return hashlib.md5((password + salt).encode()).hexdigest()

def setup_auth():
    """Setup Admin Auth"""
    # Use get_web_admin_config which now supports token
    config = config_manager.get_web_admin_config()
    token = config.get('token')
    salt = config.get('salt')
    
    # Check if we should print credentials (only in child process or if not debugging)
    should_print = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'

    if not token or not salt:
        # Generate new credentials
        plain_password = secrets.token_hex(12) # 24 chars
        salt = secrets.token_hex(4) # 8 chars
        hashed_token = hash_password(plain_password, salt)
        
        # Save back to config
        config_manager.set_web_admin_config(
            host=config['host'],
            port=config['port'],
            token=hashed_token,
            salt=salt
        )
        
        app.config['ADMIN_TOKEN'] = hashed_token
        app.config['ADMIN_SALT'] = salt
        
        if should_print:
            print("\n" + "="*50)
            print(f"WEB ADMIN INITIAL PASSWORD: {plain_password}")
            print(f"SALT: {salt}")
            print("="*50 + "\n")
            logger.info(f"Generated new admin token hash.")
    else:
        app.config['ADMIN_TOKEN'] = token
        app.config['ADMIN_SALT'] = salt
        if should_print:
            logger.info(f"Loaded existing admin token (Encrypted)")
            # print("\n" + "="*50)
            # print(f"WEB ADMIN ACCESS TOKEN: (HIDDEN)")
            # print("="*50 + "\n")

# Run auth setup
setup_auth()

# Session configuration
app.permanent_session_lifetime = timedelta(days=1)

@app.before_request
def check_auth():
    """Check authentication before request"""
    # Allow API endpoints to bypass session auth (they should use tokens if needed, but for now we open them for client sync)
    allowed_endpoints = ['login', 'static', 'face_image', 'sync_config', 'api_face_sync_push', 'api_face_sync_all', 'api_face_delete', 'sync_now']
    
    # We must explicitly allow the delete method, since the endpoint name might be generated differently
    if request.path.startswith('/api/face/') and request.method == 'DELETE':
        return None
        
    if request.endpoint and request.endpoint not in allowed_endpoints:
        # Check if user is logged in
        if not session.get('logged_in'):
            return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login Page"""
    if request.method == 'POST':
        login_type = request.form.get('login_type')
        
        if login_type == 'password':
            password = request.form.get('password')
            stored_hash = app.config.get('ADMIN_TOKEN')
            salt = app.config.get('ADMIN_SALT')
            
            # Simple token verification
            if hash_password(password, salt) == stored_hash:
                session.permanent = True
                session['logged_in'] = True
                session['user'] = 'admin'
                flash('登录成功', 'success')
                
                # Log login
                db_manager.add_admin_log('admin', 'login', 'web_admin', 'Password login success', 'high')
                
                return redirect(url_for('index'))
            else:
                # Log failed login
                db_manager.add_admin_log('unknown', 'login_failed', 'web_admin', 'Password login failed', 'medium')
                flash('密码错误', 'error')
                
        elif login_type == 'face':
            image_data = request.form.get('image_data')
            if not image_data:
                flash('未接收到图像数据', 'error')
            else:
                try:
                    # Decode base64 image
                    import base64
                    # Remove header (data:image/jpeg;base64,)
                    if ',' in image_data:
                        image_data = image_data.split(',')[1]
                    
                    img_bytes = base64.b64decode(image_data)
                    nparr = np.frombuffer(img_bytes, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    
                    if img is None:
                         flash('无效的图像数据', 'error')
                    else:
                        # Use face analysis model
                        # Ensure model is loaded
                        if not hasattr(app, 'face_app') or app.face_app is None:
                             load_face_model()
                             
                        if hasattr(app, 'face_app') and app.face_app:
                            faces = app.face_app.get(img)
                            if not faces:
                                flash('未检测到人脸', 'error')
                            elif len(faces) > 1:
                                flash('检测到多张人脸，请确保只有一个人', 'error')
                            else:
                                # Get embedding
                                embedding = faces[0].embedding
                                # Find match in DB
                                # Web Admin login should ONLY match faces that are actually web admins
                                # so we need to filter the database to only 'admin' device_id faces, or
                                # at least verify the returned match has a web admin profile and high similarity.
                                # Since find_best_match searches ALL faces, it might match a regular user profile
                                # of the same person first. We need to check if ANY profile of this person is a web admin.
                                match_name, similarity, matched_device, _ = db_manager.find_best_match(embedding)
                                
                                if match_name and similarity > 0.6:
                                    # Check if admin
                                    user_faces = db_manager.database.get(match_name, [])
                                    is_web_admin = any(f.get('device_id') == 'admin' for f in user_faces)
                                    
                                    if is_web_admin:
                                        session.permanent = True
                                        session['logged_in'] = True
                                        session['user'] = match_name
                                        session['user_avatar_device'] = 'admin' # Store this to force fetching admin avatar
                                        flash(f'欢迎回来, {match_name}', 'success')
                                        
                                        # Log login
                                        db_manager.add_admin_log(match_name, 'login', 'web_admin', 'Face login success', 'high')
                                        
                                        return redirect(url_for('index'))
                                    else:
                                        # Log failed login
                                        db_manager.add_admin_log(match_name, 'login_failed', 'web_admin', 'Face login failed: Not admin', 'medium')
                                        flash(f'用户 {match_name} 不是管理员', 'error')
                                else:
                                    flash('未匹配到已知用户', 'error')
                        else:
                             flash('人脸识别模型加载失败，请联系管理员', 'error')
                             
                except Exception as e:
                    flash(f'登录失败: {e}', 'error')
                    logger.error(f"Login error: {e}")
                    
        # If POST failed, redirect back to login (flashed messages will show)
        return redirect(url_for('login'))
        
    # GET request
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logout"""
    user = session.get('user', 'unknown')
    db_manager.add_admin_log(user, 'logout', 'web_admin', 'User logged out', 'normal')
    session.clear()
    flash('已退出登录', 'info')
    return redirect(url_for('login'))

# --- Routes ---

@app.route('/')
def index():
    """Dashboard"""
    total_users = 0
    all_names = db_manager.get_all_names()
    for name in all_names:
        user_faces = db_manager.database.get(name, [])
        total_users += len(user_faces)
    
    # Get device stats
    devices = db_manager.get_all_devices()
    online_devices = sum(1 for d in devices if d.get('is_online'))
    total_devices = len(devices)
    
    # Get today's attendance count
    attendance_records = db_manager.get_attendance_records(limit=1000)
    today_attendance = 0
    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    for record in attendance_records:
        if str(record[2]).startswith(today_str):
            today_attendance += 1

    # Get today's access count
    access_records = db_manager.get_access_records(limit=1000)
    today_access = 0
    for record in access_records:
        # Schema: id, user_name, timestamp, direction, status, ...
        # record[2] is timestamp
        if str(record[2]).startswith(today_str) and str(record[4]) == "Allowed":
            today_access += 1

    current_mode = config_manager.get_mode()
    mysql_config = config_manager.get_mysql_config()
    
    return render_template('index.html', 
                           total_users=total_users, 
                           today_attendance=today_attendance,
                           today_access=today_access,
                           current_mode=current_mode,
                           mysql_host=mysql_config['host'],
                           online_devices=online_devices,
                           total_devices=total_devices)

@app.route('/statistics')
def statistics():
    """Statistics Page with advanced time filtering"""
    from datetime import datetime, timedelta
    
    time_range = request.args.get('time_range', 'today')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    device_id = request.args.get('device_id', 'all')
    
    start_date = None
    end_date = None
    
    now = datetime.now()
    today = now.date()
    
    if time_range == 'today':
        start_date = datetime.combine(today, datetime.min.time())
        end_date = now
    elif time_range == 'yesterday':
        start_date = datetime.combine(today - timedelta(days=1), datetime.min.time())
        end_date = datetime.combine(today - timedelta(days=1), datetime.max.time())
    elif time_range == 'this_week':
        start_date = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
        end_date = now
    elif time_range == 'this_month':
        start_date = datetime.combine(today.replace(day=1), datetime.min.time())
        end_date = now
    elif time_range == 'last_month':
        last_month_end = today.replace(day=1) - timedelta(days=1)
        start_date = datetime.combine(last_month_end.replace(day=1), datetime.min.time())
        end_date = datetime.combine(last_month_end, datetime.max.time())
    elif time_range == 'this_year':
        start_date = datetime.combine(today.replace(month=1, day=1), datetime.min.time())
        end_date = now
    elif time_range == 'last_week':
        # Last week (Monday to Sunday)
        start_of_this_week = today - timedelta(days=today.weekday())
        start_date = datetime.combine(start_of_this_week - timedelta(days=7), datetime.min.time())
        end_date = datetime.combine(start_of_this_week - timedelta(days=1), datetime.max.time())
    elif time_range == 'last_year':
        last_year_end = today.replace(month=1, day=1) - timedelta(days=1)
        start_date = datetime.combine(last_year_end.replace(month=1, day=1), datetime.min.time())
        end_date = datetime.combine(last_year_end, datetime.max.time())
    elif time_range == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%dT%H:%M')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            pass
            
    # Format for DB
    s_str = start_date.strftime('%Y-%m-%d %H:%M:%S') if start_date else None
    e_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else None
    
    stats = db_manager.get_statistics(start_date=s_str, end_date=e_str, device_id=device_id)
    cloud_devices = db_manager.get_all_devices()
    
    return render_template('statistics.html', 
                           stats=stats, 
                           time_range=time_range,
                           start_date=start_date_str,
                           end_date=end_date_str,
                           selected_device=device_id,
                           cloud_devices=cloud_devices)

@app.route('/device_management')
def device_management():
    """Device Management Page"""
    local_device = db_manager.get_local_device_info()
    cloud_devices = db_manager.get_all_devices()
    return render_template('devices.html', local_device=local_device, devices=cloud_devices)

@app.route('/devices/delete/<device_id>', methods=['POST'])
def delete_device(device_id):
    """Unbind device"""
    user = session.get('user', 'admin')
    
    # Prevent unbinding the local device
    local_device = db_manager.get_local_device_info()
    if local_device and local_device.get('device_id') == device_id:
        db_manager.add_admin_log(user, 'delete_device_failed', device_id, 'Attempted to unbind local device', 'medium')
        flash('不能解绑本机设备', 'error')
        return redirect(url_for('device_management'))
        
    if db_manager.delete_device(device_id):
        db_manager.add_admin_log(user, 'delete_device', device_id, 'Device unbound', 'high')
        flash('设备已解绑', 'success')
    else:
        db_manager.add_admin_log(user, 'delete_device_failed', device_id, 'Failed to unbind device', 'medium')
        flash('解绑失败', 'error')
    return redirect(url_for('device_management'))

@app.route('/api/device_settings/<device_id>', methods=['GET', 'POST'])
def device_settings_api(device_id):
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    if request.method == 'GET':
        details = db_manager.get_device_details(device_id)
        if details:
            return jsonify({
                'success': True, 
                'business_mode': details.get('business_mode', 'Test'),
                'startup_mode': details.get('startup_mode', 'Sync')
            })
        return jsonify({'success': False, 'message': 'Device not found'}), 404
        
    elif request.method == 'POST':
        data = request.json
        business_mode = data.get('business_mode')
        startup_mode = data.get('startup_mode')
        
        # update server db
        from datetime import datetime
        updated_at = datetime.now().timestamp()
        if db_manager.update_device_config(device_id, business_mode, startup_mode, updated_at):
            return jsonify({'success': True, 'message': 'Settings updated'})
        return jsonify({'success': False, 'message': 'Failed to update settings'}), 500

@app.route('/api/device_details/<device_id>')
def device_details(device_id):
    """Get device details JSON"""
    details = db_manager.get_device_details(device_id)
    if details:
        return jsonify({'success': True, 'data': details})
    return jsonify({'success': False, 'message': 'Device not found'})

@app.route('/run_logs')
def run_logs():
    """Run Logs Page"""
    page = int(request.args.get('page', 1))
    per_page = 50
    offset = (page - 1) * per_page
    logs = db_manager.get_system_logs(limit=per_page, offset=offset)
    
    # Simple formatting for logs
    formatted_logs = []
    for log in logs:
        formatted_logs.append({
            'id': log[0],
            'level': log[1],
            'message': log[2],
            'time': log[3],
            'module': log[4],
            'device_id': log[5] if len(log) > 5 else 'local'
        })
        
    return render_template('logs.html', logs=formatted_logs, page=page)

@app.route('/api/clear_logs', methods=['POST'])
def clear_logs():
    """Clear logs"""
    log_type = request.form.get('type', 'system')
    user = session.get('user', 'admin')
    
    # Allow clearing admin logs too
    if log_type not in ['system', 'admin']:
         flash('无效的日志类型', 'error')
         return redirect(request.referrer)

    if db_manager.clear_logs(log_type):
        db_manager.add_admin_log(user, 'clear_logs', log_type, 'Logs cleared', 'high')
        flash('日志已清空', 'success')
    else:
        db_manager.add_admin_log(user, 'clear_logs_failed', log_type, 'Failed to clear logs', 'medium')
        flash('清空失败', 'error')
    return redirect(request.referrer)

@app.route('/faces')
def faces():
    """Face Management Page"""
    names = db_manager.get_all_names()
    users = []
    
    # Get Templates and Enums
    templates = config_manager.get_templates()
    enums = config_manager.get_enums()
    current_template = request.args.get('template', 'company')
    
    selected_device = request.args.get('device_id', 'all')
    search_name = request.args.get('search_name', '').strip()
    filter_group = request.args.get('filter_group', 'all')
    filter_list_type = request.args.get('filter_list_type', 'all')
    cloud_devices = db_manager.get_all_devices()
    
    for name in names:
        user_faces = db_manager.database.get(name, [])
        for face_data in user_faces:
            groups = face_data.get('groups', 'all')
            list_type = face_data.get('list_type', 'white')
            metadata = face_data.get('metadata', {})
            device_id = face_data.get('device_id')
            has_image = db_manager.check_face_image_exists(name, device_id)
            is_admin = metadata.get('is_admin', False)
            
            # Apply search and filters
            if search_name and search_name.lower() not in name.lower():
                continue
                
            if filter_group != 'all':
                if groups != 'all' and filter_group not in [g.strip() for g in groups.split(',')]:
                    continue
                    
            if filter_list_type != 'all':
                if list_type != filter_list_type:
                    continue

            # Filter by selected device for normal list
            if selected_device == 'admin':
                if device_id != 'admin':
                    continue
            elif selected_device != 'all':
                if selected_device != device_id:
                    continue

            users.append({
                'name': name,
                'is_admin': is_admin,
                'has_image': has_image,
                'groups': groups,
                'list_type': list_type,
                'metadata': metadata,
                'device_id': device_id
            })
        
    return render_template('faces.html', users=users, admins=getattr(db_manager, 'admin_users', []),
                           templates=templates, enums=enums, 
                           current_template=current_template,
                           cloud_devices=cloud_devices,
                           selected_device=selected_device,
                           search_name=search_name,
                           filter_group=filter_group,
                           filter_list_type=filter_list_type)

@app.route('/faces/add', methods=['POST'])
def add_face():
    """Add new face"""
    user = session.get('user', 'admin')
    name = request.form.get('name')
    if not name:
        flash('姓名不能为空', 'error')
        return redirect(url_for('faces'))
        
    groups = request.form.getlist('groups') # Multi-select
    groups_str = ",".join(groups) if groups else "all"
    list_type = request.form.get('list_type', 'white')
    device_id = request.form.get('device_id', 'admin')
    
    # Check image file
    if 'image' not in request.files:
        flash('未找到图片文件', 'error')
        return redirect(url_for('faces'))
        
    file = request.files['image']
    if file.filename == '':
        flash('未选择图片', 'error')
        return redirect(url_for('faces'))

    # Collect dynamic metadata based on config
    metadata = {}
    templates = config_manager.get_templates()
    
    # We collect from ALL possible templates, because user might have filled both sections
    for template_type in templates:
        for field in templates[template_type]:
            field_name = field['name']
            # Try prefixed name first, then raw name
            prefixed_key = f"{template_type}_{field_name}"
            
            # Handle multiselect
            if field['type'] == 'multiselect':
                if prefixed_key in request.form or (prefixed_key not in request.form and request.form.getlist(prefixed_key)):
                     values = request.form.getlist(prefixed_key)
                     if not values: # Try fallback
                         values = request.form.getlist(field_name)
                     if values:
                         metadata[prefixed_key] = ",".join(values)
            else:
                value = request.form.get(prefixed_key)
                if not value:
                    value = request.form.get(field_name) # Fallback
                
                if value:
                    metadata[prefixed_key] = value # Store with prefix to avoid collision
    
    if file:
        try:
            # Read image for face detection
            import numpy as np
            import cv2
            from insightface.app import FaceAnalysis
            
            # Reset pointer
            file.seek(0)
            img_bytes = file.read()
            nparr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                 flash('无效的图片文件', 'error')
                 return redirect(url_for('faces'))
            
            # Use preloaded model
            if not hasattr(app, 'face_app') or app.face_app is None:
                # Fallback to load
                from insightface.app import FaceAnalysis
                app.face_app = FaceAnalysis(providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
                app.face_app.prepare(ctx_id=0, det_size=(640, 640))
            
            # Detect face
            faces = app.face_app.get(img)
            
            if not faces:
                flash('未检测到人脸，请更换图片', 'error')
                return redirect(url_for('faces'))
            
            if len(faces) > 1:
                flash('检测到多张人脸，请确保图片只有一个人', 'error')
                return redirect(url_for('faces'))
            
            # Add face to DB
            db_manager.add_face(name, faces[0].embedding, face_image=img, groups=groups_str, list_type=list_type, metadata=metadata, device_id=device_id)
            db_manager.add_admin_log(user, 'add_face', name, f'Groups: {groups_str}, List: {list_type}, Device: {device_id}', 'high')
            flash(f'成功添加用户: {name}', 'success')
            
        except Exception as e:
            db_manager.add_admin_log(user, 'add_face_failed', name, str(e), 'medium')
            flash(f'添加失败: {e}', 'error')
            
    return redirect(url_for('faces'))

@app.route('/faces/edit', methods=['POST'])
def edit_face():
    """Edit face metadata"""
    user = session.get('user', 'admin')
    name = request.form.get('name')
    device_id = request.form.get('device_id', 'admin')
    if not name:
        flash('Missing user name', 'error')
        return redirect(url_for('faces'))
        
    # Permission Check: Sub-admin cannot edit Web admins (device_id == 'admin')
    if user != 'admin' and device_id == 'admin':
        flash('您没有权限编辑Web管理员的信息', 'error')
        return redirect(url_for('faces'))
        
    user_faces = db_manager.database.get(name, [])
    user_data = next((f for f in user_faces if f.get('device_id', 'admin') == device_id), None)
    
    if not user_data:
        flash(f'User {name} on device {device_id} not found', 'error')
        return redirect(url_for('faces'))
    
    # Existing data
    embedding = user_data.get('embedding')
    
    # Get groups from form or existing
    if 'groups' in request.form:
        groups_list = request.form.getlist('groups')
        groups = ",".join(groups_list) if groups_list else "all"
    else:
        groups = user_data.get('groups', 'all')
        
    # Get list_type from form or existing
    list_type = request.form.get('list_type', user_data.get('list_type', 'white'))
    
    current_metadata = user_data.get('metadata', {})
    # No need to get device_id from form again, we already have it from the query
    
    # Collect new metadata
    new_metadata = current_metadata.copy()
    templates = config_manager.get_templates()
    
    for template_type in templates:
        for field in templates[template_type]:
            field_name = field['name']
            prefixed_key = f"{template_type}_{field_name}"
            
            # Handle multiselect
            if field['type'] == 'multiselect':
                if prefixed_key in request.form or (prefixed_key not in request.form and request.form.getlist(prefixed_key)):
                     # Checkboxes are tricky: if unchecked, they don't send anything.
                     # But we iterate templates. If it's a multiselect, we should check getlist
                     values = request.form.getlist(prefixed_key)
                     new_metadata[prefixed_key] = ",".join(values) # Update even if empty string
            
            # Check if field exists in form (even if empty)
            elif prefixed_key in request.form:
                value = request.form.get(prefixed_key)
                new_metadata[prefixed_key] = value
                
    try:
        db_manager.add_face(name, embedding, groups=groups, list_type=list_type, metadata=new_metadata, device_id=device_id)
        db_manager.add_admin_log(user, 'edit_face', name, f'Updated metadata', 'normal')
        flash(f'Updated details for {name}', 'success')
    except Exception as e:
        db_manager.add_admin_log(user, 'edit_face_failed', name, str(e), 'medium')
        flash(f'Failed to update: {e}', 'error')
        
    return redirect(url_for('faces'))

@app.route('/faces/delete/<name>/<device_id>', methods=['GET', 'POST'])
def delete_face(name, device_id):
    """Delete face"""
    user = session.get('user', 'admin')
    
    # Permission Check: Sub-admin cannot delete Web admins
    if user != 'admin' and device_id == 'admin':
        flash('您没有权限删除Web管理员', 'error')
        return redirect(url_for('faces'))
        
    if db_manager.delete_face(name, device_id):
        db_manager.add_admin_log(user, 'delete_face', name, f'Face deleted on device {device_id}', 'high')
        flash(f'Deleted user: {name} from {device_id}', 'success')
    else:
        db_manager.add_admin_log(user, 'delete_face_failed', name, 'Failed to delete face', 'medium')
        flash(f'Failed to delete user: {name}', 'error')
    return redirect(url_for('faces'))

@app.route('/faces/toggle_admin/<name>', methods=['GET', 'POST'])
def toggle_admin(name):
    """Toggle edge device admin status via metadata"""
    user = session.get('user', 'admin')
    
    device_id = request.args.get('device_id')
    action = request.args.get('action', '')
    
    # Permission Check: Sub-admin cannot toggle Web admins
    if user != 'admin' and device_id == 'admin':
        flash('您没有权限操作Web管理员', 'error')
        return redirect(url_for('faces'))
    
    if not device_id:
        flash('未指定设备ID', 'error')
        return redirect(url_for('faces'))
        
    user_faces = db_manager.database.get(name, [])
    user_data = next((f for f in user_faces if f.get('device_id') == device_id), None)
    
    if not user_data:
        flash('未找到该设备下的人脸', 'error')
        return redirect(url_for('faces'))
        
    metadata = user_data.get('metadata', {})
    is_admin = metadata.get('is_admin', False)
        
    if is_admin:
        if action == 'grant':
            flash('该用户已经是该设备的管理员', 'info')
            return redirect(url_for('faces'))
            
        metadata['is_admin'] = False
        db_manager.add_face(name, user_data['embedding'], face_image=None, groups=user_data.get('groups', 'all'), list_type=user_data.get('list_type', 'white'), metadata=metadata, device_id=device_id)
        db_manager.add_admin_log(user, 'remove_admin', name, f'Removed admin rights on {device_id}', 'high')
        flash(f'已移除 {name} 在设备 {device_id} 上的管理员权限', 'success')
    else:
        if action == 'revoke':
            return redirect(url_for('faces'))
            
        metadata['is_admin'] = True
        db_manager.add_face(name, user_data['embedding'], face_image=None, groups=user_data.get('groups', 'all'), list_type=user_data.get('list_type', 'white'), metadata=metadata, device_id=device_id)
        db_manager.add_admin_log(user, 'add_admin', name, f'Granted admin rights on {device_id}', 'high')
        flash(f'已将 {name} 设为设备 {device_id} 的管理员', 'success')
        
    return redirect(url_for('faces'))

@app.route('/face_image/<name>')
def face_image(name):
    """Serve face image"""
    device_id = request.args.get('device_id')
    
    import os
    import hashlib
    
    def get_paths(dev_id):
        safe_name = hashlib.md5(name.encode()).hexdigest()
        safe_dev = hashlib.md5(dev_id.encode()).hexdigest() if dev_id != 'admin' else 'admin'
        return f"{safe_name}_{safe_dev}.jpg", f"{safe_name}.jpg"

    if device_id:
        filename, old_filename = get_paths(device_id)
        if os.path.exists(os.path.join(db_manager.face_images_dir, filename)):
            return send_from_directory(db_manager.face_images_dir, filename)
        elif os.path.exists(os.path.join(db_manager.face_images_dir, old_filename)):
            return send_from_directory(db_manager.face_images_dir, old_filename)
            
    # Fallback to search all associated device_ids for this user
    user_faces = db_manager.database.get(name, [])
    if isinstance(user_faces, list):
        for face in user_faces:
            f_device_id = face.get('device_id', 'admin')
            filename, old_filename = get_paths(f_device_id)
            if os.path.exists(os.path.join(db_manager.face_images_dir, filename)):
                return send_from_directory(db_manager.face_images_dir, filename)
            elif os.path.exists(os.path.join(db_manager.face_images_dir, old_filename)):
                return send_from_directory(db_manager.face_images_dir, old_filename)
                
    # Final fallback to global
    filename, old_filename = get_paths('admin')
    if os.path.exists(os.path.join(db_manager.face_images_dir, filename)):
        return send_from_directory(db_manager.face_images_dir, filename)
    elif os.path.exists(os.path.join(db_manager.face_images_dir, old_filename)):
        return send_from_directory(db_manager.face_images_dir, old_filename)
        
    return "Image not found", 404

@app.route('/face_compare', methods=['GET'])
def face_compare():
    """Face Comparison Page"""
    return render_template('face_compare.html')

@app.route('/api/face_compare', methods=['POST'])
def api_face_compare():
    """API for comparing two uploaded face images"""
    try:
        if 'image1' not in request.files or 'image2' not in request.files:
            return jsonify({'success': False, 'message': '请上传两张图片'}), 400
            
        file1 = request.files['image1']
        file2 = request.files['image2']
        
        if file1.filename == '' or file2.filename == '':
            return jsonify({'success': False, 'message': '请选择两张图片'}), 400

        # Ensure model is loaded
        if not hasattr(app, 'face_app') or app.face_app is None:
             load_face_model()
             
        if not hasattr(app, 'face_app') or app.face_app is None:
            return jsonify({'success': False, 'message': '人脸识别模型加载失败'}), 500

        def get_embedding(file):
            import numpy as np
            import cv2
            
            file.seek(0)
            img_bytes = file.read()
            nparr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                return None, "无效的图片文件"
                
            faces = app.face_app.get(img)
            if not faces:
                return None, "未检测到人脸"
            if len(faces) > 1:
                # 默认取最大的人脸
                faces.sort(key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]), reverse=True)
                
            return faces[0].embedding, None

        emb1, err1 = get_embedding(file1)
        if err1:
            return jsonify({'success': False, 'message': f'图1错误: {err1}'}), 400
            
        emb2, err2 = get_embedding(file2)
        if err2:
            return jsonify({'success': False, 'message': f'图2错误: {err2}'}), 400

        # Compute cosine similarity
        from numpy.linalg import norm
        import numpy as np
        
        # Flatten and compute
        emb1 = np.array(emb1).flatten()
        emb2 = np.array(emb2).flatten()
        
        similarity = np.dot(emb1, emb2) / (norm(emb1) * norm(emb2))
        similarity_score = float(similarity)
        
        # Default threshold in arcface is usually around 0.5 - 0.6
        threshold = 0.6
        is_match = similarity_score >= threshold
        
        return jsonify({
            'success': True,
            'similarity': round(similarity_score, 4),
            'is_match': is_match,
            'threshold': threshold
        })

    except Exception as e:
        logger.error(f"Face compare API error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/sync_now', methods=['POST'])
def sync_now():
    """Trigger manual sync"""
    try:
        success = db_manager.sync_data_now()
        if success:
            return jsonify({'success': True, 'message': '同步成功'})
        else:
            return jsonify({'success': False, 'message': '同步失败，请检查日志'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/records')
def records():
    """Records Query Page"""
    record_type = request.args.get('type', 'attendance')
    page = int(request.args.get('page', 1))
    
    # Filter parameters
    time_range = request.args.get('time_range', 'today')
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    device_id_filter = request.args.get('device_id', '')
    
    per_page = 20
    offset = (page - 1) * per_page
    
    # Date Filtering
    start_date = None
    end_date = None
    from datetime import datetime, timedelta
    now = datetime.now()
    today = now.date()
    
    if time_range == 'today':
        start_date = datetime.combine(today, datetime.min.time())
        end_date = now
    elif time_range == 'yesterday':
        start_date = datetime.combine(today - timedelta(days=1), datetime.min.time())
        end_date = datetime.combine(today - timedelta(days=1), datetime.max.time())
    elif time_range == 'this_week':
        start_date = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
        end_date = now
    elif time_range == 'this_month':
        start_date = datetime.combine(today.replace(day=1), datetime.min.time())
        end_date = now
    elif time_range == 'custom':
        start_time_str = request.args.get('start_time')
        end_time_str = request.args.get('end_time')
        
        if start_time_str:
            try:
                # datetime-local sends format: YYYY-MM-DDTHH:MM
                # but we added step=1 so it might be YYYY-MM-DDTHH:MM:SS
                start_date = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M:%S')
            except ValueError:
                try:
                    start_date = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M')
                except:
                    pass
                    
        if end_time_str:
            try:
                end_date = datetime.strptime(end_time_str, '%Y-%m-%dT%H:%M:%S')
            except ValueError:
                try:
                    end_date = datetime.strptime(end_time_str, '%Y-%m-%dT%H:%M')
                except:
                    pass
    
    start_str = start_date.strftime('%Y-%m-%d %H:%M:%S') if start_date else None
    end_str = end_date.strftime('%Y-%m-%d %H:%M:%S') if end_date else None
    
    # Pass start/end time back to template for form value
    form_start_time = start_date.strftime('%Y-%m-%dT%H:%M:%S') if start_date else ''
    form_end_time = end_date.strftime('%Y-%m-%dT%H:%M:%S') if end_date else ''
    
    data = []
    if record_type == 'attendance':
        rows = db_manager.get_attendance_records(limit=per_page, offset=offset, 
                                                    start_date=start_str, end_date=end_str, 
                                                    search=search_query, device_id=device_id_filter)
        # Convert rows to dict
        for row in rows:
            # id, user_name, timestamp, status, remarks, device_id, sync_status, sync_timestamp
            # Note: The order depends on SELECT * from sqlite.
            # Schema: id, user_name, timestamp, status, remarks, device_id, sync_status, sync_timestamp
            # Indices: 0, 1, 2, 3, 4, 5, 6, 7
            entry = {'id': row[0], 'name': row[1], 'time': row[2], 'status': row[3], 'remark': row[4]}
            if len(row) > 5:
                entry['device_id'] = row[5]
            if len(row) > 6:
                entry['sync_status'] = row[6]
            data.append(entry)
    elif record_type == 'access':
        rows = db_manager.get_access_records(limit=per_page, offset=offset, 
                                                start_date=start_str, end_date=end_str, 
                                                search=search_query, status=status_filter, device_id=device_id_filter)
        for row in rows:
            # id, user_name, timestamp, direction, status, remarks, device_id, sync_status, sync_timestamp
            # Indices: 0, 1, 2, 3, 4, 5, 6, 7, 8
            entry = {'id': row[0], 'name': row[1], 'time': row[2], 'direction': row[3], 'status': row[4], 'remark': row[5]}
            if len(row) > 6:
                entry['device_id'] = row[6]
            if len(row) > 7:
                entry['sync_status'] = row[7]
            data.append(entry)
    elif record_type == 'admin':
        rows = db_manager.get_admin_logs(limit=per_page, offset=offset, 
                                            start_date=start_str, end_date=end_str, 
                                            search=search_query, device_id=device_id_filter)
        for row in rows:
            # id, admin_name, action, target, details, sensitivity, timestamp, device_id, sync_status, sync_timestamp
            entry = {
                'id': row[0], 'admin': row[1], 'action': row[2], 'target': row[3], 
                'details': row[4], 'sensitivity': row[5], 'time': row[6]
            }
            if len(row) > 7:
                entry['device_id'] = row[7]
            if len(row) > 8:
                entry['sync_status'] = row[8]
            data.append(entry)
    elif record_type == 'system':
        # Apply filtering to system logs too
        rows = db_manager.get_system_logs(limit=per_page, offset=offset, device_id=device_id_filter)
        for row in rows:
            # id, level, message, timestamp, module, device_id, sync_status, sync_timestamp
            entry = {
                'id': row[0], 'level': row[1], 'message': row[2], 
                'time': row[3], 'module': row[4]
            }
            if len(row) > 5:
                entry['device_id'] = row[5]
                entry['sync_status'] = row[6]
            data.append(entry)
            
    return render_template('records.html', records=data, record_type=record_type, page=page,
                           time_range=time_range, search_query=search_query, status_filter=status_filter,
                           device_id_filter=device_id_filter,
                           start_time=form_start_time, end_time=form_end_time)

@app.route('/settings/general', methods=['GET', 'POST'])
def settings_general():
    """General Settings Page"""
    user = session.get('user', 'admin')
    if request.method == 'POST':
        sync_interval = request.form.get('sync_interval')

        if sync_interval is not None:
             try:
                 interval = int(sync_interval)
                 config_manager.set_sync_interval(interval)
             except ValueError:
                 pass

        db_manager.add_admin_log(user, 'settings_update', 'general', f'Sync: {sync_interval}', 'medium')
        flash('General settings updated successfully', 'success')
        return redirect(url_for('settings_general'))
    
    sync_interval = config_manager.get_sync_interval()
    return render_template('settings/general.html', 
                           sync_interval=sync_interval)

@app.route('/settings/enums', methods=['GET', 'POST'])
def settings_enums():
    """Enum Settings Page"""
    user = session.get('user', 'admin')
    if request.method == 'POST':
        key = request.form.get('key')
        values = request.form.get('values')
        
        if key and values:
            # Simple validation
            val_list = [v.strip() for v in values.split(',')]
            config_manager.update_enum(key, val_list)
            db_manager.add_admin_log(user, 'settings_update', 'enums', f'Updated {key}: {values}', 'medium')
            flash(f'Updated enum: {key}', 'success')
        return redirect(url_for('settings_enums'))

    enums = config_manager.get_enums()
    return render_template('settings/enums.html', enums=enums)

@app.route('/settings/database', methods=['GET', 'POST'])
def settings_database():
    """Database Settings Page"""
    user = session.get('user', 'admin')
    if request.method == 'POST':
        host = request.form.get('db_host')
        port = request.form.get('db_port')
        user_db = request.form.get('db_user')
        password = request.form.get('db_password')
        database = request.form.get('db_name')
        
        try:
            port = int(port)
            config_manager.set_mysql_config(host, user_db, password, database, port)
            db_manager.add_admin_log(user, 'settings_update', 'database', f'Updated MySQL config: {host}', 'high')
            flash('Database settings updated successfully', 'success')
        except ValueError:
            flash('Invalid port number', 'error')
            
        return redirect(url_for('settings_database'))

    mysql_config = config_manager.get_mysql_config()
    return render_template('settings/database.html', mysql_config=mysql_config)

@app.route('/settings/security', methods=['GET', 'POST'])
def settings_security():
    """Security Settings Page - Change Token"""
    user = session.get('user', 'admin')
    if request.method == 'POST':
        new_token = request.form.get('new_token')
        confirm_token = request.form.get('confirm_token')
        
        if not new_token or not confirm_token:
            flash('请输入新密码', 'error')
            return redirect(url_for('settings_security'))
            
        if new_token != confirm_token:
            flash('两次输入的密码不一致', 'error')
            return redirect(url_for('settings_security'))
            
        # Update config
        config = config_manager.get_web_admin_config()
        
        # Get or create salt
        salt = config.get('salt')
        if not salt:
            salt = secrets.token_hex(4)
            
        # Hash new password
        hashed_token = hash_password(new_token, salt)
        
        config_manager.set_web_admin_config(
            host=config['host'],
            port=config['port'],
            token=hashed_token,
            salt=salt
        )
        
        # Update runtime config
        app.config['ADMIN_TOKEN'] = hashed_token
        app.config['ADMIN_SALT'] = salt
        
        db_manager.add_admin_log(user, 'settings_update', 'security', 'Password changed', 'high')
        flash('管理员密码已修改', 'success')
        return redirect(url_for('settings_security'))
        
    return render_template('settings/security.html')

@app.route('/settings/about')
def settings_about():
    """About Page - Renders README.md"""
    import markdown
    from markdown.extensions.md_in_html import MarkdownInHtmlExtension
    from markdown.extensions.attr_list import AttrListExtension
    
    readme_path = os.path.join(BASE_DIR, 'README.md')
    content = ""
    
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            text = f.read()
            # 开启所有的 HTML 块内 Markdown 解析支持
            md = markdown.Markdown(extensions=[
                'fenced_code', 
                'tables', 
                'toc', 
                MarkdownInHtmlExtension(), 
                AttrListExtension()
            ])
            content = md.convert(text)
    else:
        content = "<p class='text-danger'>README.md not found.</p>"
        
    return render_template('settings/about.html', content=content)

# Legacy route redirect
@app.route('/settings')
def settings():
    return redirect(url_for('settings_general'))

@app.route('/api/sync_config')
def sync_config():
    """API to sync configuration to clients"""
    try:
        device_id = request.args.get('device_id')
        client_mode = request.args.get('client_mode')
        client_start_mode = request.args.get('client_start_mode')
        client_updated_at = request.args.get('client_updated_at')

        # Global config
        mode = config_manager.get_mode()
        start_mode = config_manager.get_start_mode()
        mysql_config = config_manager.get_mysql_config()
        
        if device_id:
            # Check device config
            device_details = db_manager.get_device_details(device_id)
            if device_details:
                server_mode = device_details.get('business_mode')
                server_start_mode = device_details.get('startup_mode')
                server_updated_at = device_details.get('config_updated_at')
                
                # If both are valid, resolve conflict
                if client_updated_at and server_updated_at:
                    try:
                        client_time = float(client_updated_at)
                        server_time = float(server_updated_at)
                        
                        if client_time > server_time:
                            # Client is newer, update server
                            db_manager.update_device_config(device_id, client_mode, client_start_mode, client_time)
                            mode = client_mode
                            start_mode = client_start_mode
                        else:
                            # Server is newer, send server config
                            if server_mode and server_mode != 'None':
                                mode = server_mode
                            if server_start_mode and server_start_mode != 'None':
                                start_mode = server_start_mode
                    except ValueError:
                        pass
                else:
                    # If client doesn't have updated_at or server doesn't, we prefer server if set
                    if server_mode and server_mode != 'None':
                        mode = server_mode
                    if server_start_mode and server_start_mode != 'None':
                        start_mode = server_start_mode
        
        return jsonify({
            'success': True,
            'mode': mode,
            'start_mode': start_mode,
            'mysql': mysql_config
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/face/sync/push', methods=['POST'])
def api_face_sync_push():
    """
    Proxy API to receive face data from client and update server DB.
    This mimics the FastAPI structure to keep clients happy without changing their URL logic.
    """
    try:
        # Extract data
        name = request.form.get('name')
        groups = request.form.get('groups', 'all')
        list_type = request.form.get('list_type', 'white')
        metadata_str = request.form.get('metadata', '{}')
        device_id = request.form.get('device_id')
        
        if not name:
            logger.error('Missing name')
            return jsonify({'message': 'Missing name'}), 400
            
        import json
        try:
            metadata = json.loads(metadata_str)
        except:
            metadata = {}
            
        file = request.files.get('file')
        full_image_file = request.files.get('full_image')
        
        embedding_b64 = request.form.get('embedding')
        embedding = None
        if embedding_b64:
            import base64
            import pickle
            try:
                embedding = pickle.loads(base64.b64decode(embedding_b64))
            except Exception as e:
                logger.error(f"Failed to decode embedding: {e}")

        if file:
            # Read image for face detection
            import numpy as np
            import cv2
            
            # Reset pointer
            file.seek(0)
            img_bytes = file.read()
            nparr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                 logger.error('Invalid image')
                 return jsonify({'message': 'Invalid image'}), 400
            
            if embedding is None:
                # Use app.face_app
                if not hasattr(app, 'face_app') or app.face_app is None:
                     load_face_model()
                     
                # Detect face on crop
                faces = app.face_app.get(img)
                
                if not faces:
                    # Try detection on full image if provided
                    if full_image_file:
                        try:
                            full_image_file.seek(0)
                            full_bytes = full_image_file.read()
                            full_nparr = np.frombuffer(full_bytes, np.uint8)
                            full_img = cv2.imdecode(full_nparr, cv2.IMREAD_COLOR)
                            
                            if full_img is not None:
                                faces_full = app.face_app.get(full_img)
                                if faces_full:
                                    faces_full.sort(key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]), reverse=True)
                                    embedding = faces_full[0].embedding
                                    logger.info(f"Face detected in full image for {name}")
                                    
                                    # Save full image as requested
                                    full_dir = os.path.join(FACE_IMAGES_DIR, "full")
                                    if not os.path.exists(full_dir):
                                        os.makedirs(full_dir)
                                    safe_name = hashlib.md5(name.encode()).hexdigest()
                                    cv2.imwrite(os.path.join(full_dir, f"{safe_name}.jpg"), full_img)
                        except Exception as e:
                            logger.error(f"Failed to process full image: {e}")

                    if embedding is None:
                        logger.error('No face detected')
                        return jsonify({'message': 'No face detected'}), 400
                
                else:
                    # Sort by size
                    faces.sort(key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]), reverse=True)
                    embedding = faces[0].embedding
            
            # Add face to DB (SyncDatabaseManager)
            # db_manager is already initialized in app.py
            
            # Handle device_id merging logic
            existing_faces = db_manager.database.get(name, [])
            if not isinstance(existing_faces, list):
                existing_faces = [existing_faces]
                
            db_manager.add_face(name, embedding, face_image=img, groups=groups, list_type=list_type, metadata=metadata, device_id=device_id)
            
            return jsonify({'message': f'User {name} synced successfully'})
        else:
            logger.error('Missing file')
            return jsonify({'message': 'Missing file'}), 400
            
    except Exception as e:
        logger.error(f"Sync Push Error: {e}")
        return jsonify({'message': str(e)}), 500

@app.route('/api/face/<name>', methods=['DELETE'])
def api_face_delete(name):
    """
    Proxy API to receive face deletion from client and update server DB.
    """
    try:
        device_id = request.args.get('device_id')
        
        # Check if the user exists
        if not db_manager.name_exists(name):
            return jsonify({'message': 'User not found'}), 404
            
        if db_manager.delete_face(name, device_id):
            return jsonify({'message': f'User {name} deleted successfully'})
        else:
            return jsonify({'message': 'Failed to delete user'}), 500
    except Exception as e:
        logger.error(f"Sync Delete Error: {e}")
        return jsonify({'message': str(e)}), 500

@app.route('/api/face/sync/all', methods=['GET'])
def api_face_sync_all():
    """
    API to provide all faces to clients (Pull).
    """
    try:
        request_device_id = request.args.get('device_id')
        users = []
        
        # db_manager.database is a dict mapping name to a list of face dicts
        for name, face_list in db_manager.database.items():
            if not isinstance(face_list, list):
                # Handle legacy data structure if any
                face_list = [face_list]
                
            for face_data in face_list:
                metadata = face_data.get('metadata', {})
                groups = face_data.get('groups', 'all')
                list_type = face_data.get('list_type', 'white')
                embedding = face_data.get('embedding')
                face_device_id = face_data.get('device_id', 'admin')
                
                if embedding is None:
                    continue
                    
                # Convert embedding to list for JSON serialization
                if isinstance(embedding, np.ndarray):
                    embedding_list = embedding.tolist()
                else:
                    embedding_list = list(embedding)
                    
                # Get face image if exists - pass the correct face_device_id
                face_image_b64 = None
                import base64
                if db_manager.check_face_image_exists(name, face_device_id):
                    img = db_manager.load_face_image(name, face_device_id)
                    if img is not None:
                        _, buffer = cv2.imencode('.jpg', img)
                        face_image_b64 = base64.b64encode(buffer).decode('utf-8')
                
                users.append({
                    "name": name,
                    "embedding": embedding_list,
                    "groups": groups,
                    "list_type": list_type,
                    "metadata": metadata,
                    "is_admin": metadata.get('is_admin', False),
                    "face_image": face_image_b64,
                    "device_id": face_device_id
                })
            
        return jsonify(users)
    except Exception as e:
        logger.error(f"Sync Pull Error: {e}")
        return jsonify({'message': str(e)}), 500

if __name__ == '__main__':
    load_dotenv(find_dotenv())
    # context = (r'C:\Users\yang\localhost.pem', r'C:\Users\yang\localhost-key.pem')
    flask_port = int(os.environ.get('FLASK_PORT', 5000))
    
    # 默认设置为开发环境 'development'
    flask_env = os.environ.get('FLASK_ENV', 'development')

    if flask_env == 'development':
        print(f"Starting DEVELOPMENT server on http://0.0.0.0:{flask_port}")
        # app.run(host='0.0.0.0', ssl_context=context, port=flask_port, debug=True)
        app.run(host='0.0.0.0', port=flask_port, debug=True)
    else:   # production
        from waitress import serve
        import logging
        logging.getLogger('waitress').setLevel(logging.INFO)
        print(f"Starting PRODUCTION server on http://0.0.0.0:{flask_port} using Waitress")
        serve(app, host='0.0.0.0', port=flask_port, threads=4)

