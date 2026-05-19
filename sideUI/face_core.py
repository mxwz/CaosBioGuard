import os
import sys
import pickle
import hashlib
import cv2
import numpy as np
import torch
import yaml
from collections import OrderedDict
from PIL import Image
import torchvision.transforms as transforms
from insightface.app import FaceAnalysis
from sklearn.neighbors import NearestNeighbors

# Add current directory to path for models import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    import models
except ImportError:
    pass

# Global variable for cached model
face_analysis_model = None

def mkdir_if_not_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

class FaceAntiSpoofing:
    def __init__(self, config_path, model_path, arch='moilenetv2'):
        self.config_path = config_path
        self.model_path = model_path
        self.arch = arch
        self.device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        self.model = self._load_model()

        self.normalize = transforms.Normalize(mean=[0.14300402, 0.1434545, 0.14277956],
                                             std=[0.10050353, 0.100842826, 0.10034215])
        self.ratio = 224.0 / float(224)
        self.preprocess = transforms.Compose([
            transforms.Resize(int(256 * self.ratio)),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            self.normalize,
        ])

    def _load_model(self):
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model file not found: {self.model_path}")

        with open(self.config_path, 'r') as f:
            config = yaml.load(f, Loader=yaml.FullLoader)

        if "model" in config.keys():
            model = models.__dict__[self.arch](**config['model'])
        else:
            model = models.__dict__[self.arch]()

        checkpoint = torch.load(self.model_path, map_location=self.device)
        state_dict = checkpoint['state_dict'] if 'state_dict' in checkpoint else checkpoint

        new_state_dict = OrderedDict()
        for k, v in state_dict.items():
            if k.startswith('module.'):
                name = k[7:]
            else:
                name = k
            new_state_dict[name] = v

        model.load_state_dict(new_state_dict)
        model.to(self.device)
        model.eval()
        return model

    def predict_frame(self, frame):
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb_frame)
        input_tensor = self.preprocess(pil_image)
        input_batch = input_tensor.unsqueeze(0)
        input_batch = input_batch.to(self.device)

        with torch.no_grad():
            output = self.model(input_batch)
            softmax_output = torch.softmax(output, dim=-1)
            prediction = softmax_output.cpu().numpy()[0]
            label = 'Genuine' if np.argmax(prediction) == 1 else 'Spoofing'
            return label, prediction

def preload_face_analysis_model():
    global face_analysis_model
    if face_analysis_model is None:
        try:
            ctx_id = -1
            try:
                import onnxruntime
                providers = onnxruntime.get_available_providers()
                if 'CUDAExecutionProvider' in providers:
                    ctx_id = 0
            except ImportError:
                pass

            face_analysis_model = FaceAnalysis(name='buffalo_l')
            face_analysis_model.prepare(ctx_id=ctx_id, det_size=(640, 640))
            return True, "Model loaded successfully"
        except Exception as e:
            return False, f"Model loading failed: {str(e)}"
    return True, "Model cached"

def get_face_analysis_model():
    global face_analysis_model
    if face_analysis_model is None:
        success, message = preload_face_analysis_model()
        if not success:
            raise Exception(message)
    return face_analysis_model

class FaceDatabaseManager:
    def __init__(self, database_path="D:/Arcface/dd/face_database.pkl"):
        self.database_path = database_path
        mkdir_if_not_exists("./picture")
        mkdir_if_not_exists("./face_images")
        self.face_images_dir = "./face_images"
        self.database = self.load_or_create_database()
        self.admin_users = self.load_admin_users()

    def load_or_create_database(self):
        os.makedirs(os.path.dirname(self.database_path), exist_ok=True)
        if os.path.exists(self.database_path):
            try:
                with open(self.database_path, "rb") as f:
                    return pickle.load(f)
            except Exception:
                return {}
        else:
            return {}

    def load_admin_users(self):
        admin_path = self.database_path.replace(".pkl", "_admin.pkl")
        if os.path.exists(admin_path):
            try:
                with open(admin_path, "rb") as f:
                    return pickle.load(f)
            except Exception:
                return set()
        return set()

    def save_database(self):
        with open(self.database_path, "wb") as f:
            pickle.dump(self.database, f)

        admin_path = self.database_path.replace(".pkl", "_admin.pkl")
        with open(admin_path, "wb") as f:
            pickle.dump(self.admin_users, f)

    def add_face(self, name, embedding, face_image=None):
        self.database[name] = embedding
        if face_image is not None:
            self.save_face_image(name, face_image)
        self.save_database()

    def delete_face(self, name):
        if name in self.database:
            del self.database[name]
            self.delete_face_image(name)
            if name in self.admin_users:
                self.admin_users.remove(name)
            self.save_database()
            return True
        return False

    def save_face_image(self, name, face_image):
        try:
            safe_name = hashlib.md5(name.encode()).hexdigest()
            image_path = os.path.join(self.face_images_dir, f"{safe_name}.jpg")
            cv2.imwrite(image_path, face_image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            return True
        except Exception as e:
            print(f"Failed to save face image: {str(e)}")
            return False

    def load_face_image(self, name):
        try:
            safe_name = hashlib.md5(name.encode()).hexdigest()
            image_path = os.path.join(self.face_images_dir, f"{safe_name}.jpg")
            if os.path.exists(image_path):
                return cv2.imread(image_path)
            return None
        except Exception as e:
            print(f"Failed to load face image: {str(e)}")
            return None

    def delete_face_image(self, name):
        try:
            safe_name = hashlib.md5(name.encode()).hexdigest()
            image_path = os.path.join(self.face_images_dir, f"{safe_name}.jpg")
            if os.path.exists(image_path):
                os.remove(image_path)
                return True
            return False
        except Exception as e:
            print(f"Failed to delete face image: {str(e)}")
            return False

    def check_face_image_exists(self, name):
        safe_name = hashlib.md5(name.encode()).hexdigest()
        image_path = os.path.join(self.face_images_dir, f"{safe_name}.jpg")
        return os.path.exists(image_path)

    def get_all_names(self):
        return list(self.database.keys())

    def name_exists(self, name):
        return name in self.database

    def set_as_admin(self, name):
        if name in self.database:
            self.admin_users.add(name)
            self.save_database()
            return True
        return False

    def is_admin(self, name):
        return name in self.admin_users

    def remove_admin(self, name):
        if name in self.admin_users:
            self.admin_users.remove(name)
            self.save_database()
            return True
        return False

    def build_nn_model(self):
        if not self.database:
            return None, []
        embeddings = np.array(list(self.database.values()))
        names = list(self.database.keys())
        nn_model = NearestNeighbors(n_neighbors=1, metric="cosine")
        nn_model.fit(embeddings)
        return nn_model, names

    def find_best_match(self, embedding, threshold=0.6):
        nn_model, names = self.build_nn_model()
        if nn_model is None:
            return None, 0
        distances, indices = nn_model.kneighbors([embedding])
        if distances[0][0] < threshold:
            similarity = 1 - distances[0][0]
            return names[indices[0][0]], similarity
        return None, 0

