"""X2000 命令行调试工具。

用法示例::

    python -m x2000 --port COM3 version
    python -m x2000 --port COM3 status
    python -m x2000 --port COM3 verify --timeout 10
    python -m x2000 --port COM3 enroll-face --name 张三
    python -m x2000 --port COM3 enroll-palm --name 张三
    python -m x2000 --port COM3 list
    python -m x2000 --port COM3 delete --user-id 1
    python -m x2000 --port COM3 capture --number 0
"""

from __future__ import annotations

import argparse
import sys

from . import constants as C
from .client import X2000Client, parse_face_state
from .errors import X2000Error


def _print_note(nid, payload):
    if nid == C.NID_FACE_STATE:
        st = parse_face_state(payload)
        if st:
            print('  [NOTE] 识别状态: %s (left=%d top=%d right=%d bottom=%d yaw=%d pitch=%d roll=%d)'
                  % (st.state_name, st.left, st.top, st.right, st.bottom, st.yaw, st.pitch, st.roll))
        return
    if nid == C.NID_READY:
        print('  [NOTE] 模块已就绪')
        return
    if nid == C.NID_OTA_DONE:
        print('  [NOTE] OTA 完成')
        return
    if nid == C.NID_EYE_STATE:
        print('  [NOTE] 睁闭眼状态: %s' % (payload[0] if payload else ''))
        return
    print('  [NOTE] nid=0x%02X data=%s' % (nid if nid is not None else 0, payload.hex()))


def _cmd_version(client, args):
    print('软件版本:', client.get_version())
    print('库版本:', client.get_library_version())


def _cmd_status(client, args):
    st = client.get_status()
    print('模块状态: %s (code=%d)' % (C.MODULE_STATUS_NAMES.get(st, '未知'), st))


def _cmd_verify(client, args):
    print('开始鉴权（%ds 内请对准模组）...' % args.timeout)
    r = client.verify(timeout=args.timeout, verify_mode=args.mode, on_note=_print_note)
    if r.success:
        print('识别成功: user_id=%d name=%s admin=%d unlock_status=%d'
              % (r.user_id, r.user_name, r.admin, r.unlock_status))
    else:
        print('识别失败: %s' % C.result_name(r.result))


def _cmd_enroll_face(client, args):
    print('录入人脸（方向=%s）...' % args.direction)
    r = client.enroll_face(args.name, admin=args.admin, face_direction=args.direction,
                           timeout=args.timeout, on_note=_print_note)
    if r.success:
        print('录入成功: user_id=%d face_direction=0x%02X' % (r.user_id, r.face_direction))
    else:
        print('录入失败: %s' % C.result_name(r.result))


def _cmd_enroll_palm(client, args):
    print('录入掌静脉...')
    r = client.enroll_palm(args.name, admin=args.admin, timeout=args.timeout, on_note=_print_note)
    if r.success:
        print('录入成功: user_id=%d' % r.user_id)
    else:
        print('录入失败: %s' % C.result_name(r.result))


def _cmd_list(client, args):
    ids = client.get_all_user_ids(fmt=0)
    print('已注册用户数: %d' % len(ids))
    for uid in ids:
        info = client.get_user_info(uid)
        print('  user_id=%d name=%s admin=%d' % (info.user_id, info.user_name, info.admin))


def _cmd_delete(client, args):
    client.delete_user(args.user_id, user_type=args.user_type)
    print('已删除 user_id=%d' % args.user_id)


def _cmd_delete_all(client, args):
    client.delete_all(delete_type=args.type)
    print('已批量删除 (type=%d)' % args.type)


def _cmd_capture(client, args):
    data = client.capture_image(image_number=args.number, width=args.width, height=args.height)
    if not data:
        print('未获取到图片')
        return
    out = args.output or ('x2000_%d.jpg' % args.number)
    with open(out, 'wb') as f:
        f.write(data)
    print('已保存图片: %s (%d 字节)' % (out, len(data)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='X2000 模组串口调试工具')
    parser.add_argument('--port', '-p', required=True, help='串口设备，如 COM3 / /dev/ttyUSB0')
    parser.add_argument('--baudrate', '-b', type=int, default=115200, help='波特率，默认 115200')
    parser.add_argument('--encoding', default='utf-8', help='用户名编码，默认 utf-8')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('version', help='获取版本').set_defaults(func=_cmd_version)
    sub.add_parser('status', help='获取模块状态').set_defaults(func=_cmd_status)

    p = sub.add_parser('verify', help='鉴权解锁')
    p.add_argument('--timeout', type=int, default=10)
    p.add_argument('--mode', type=int, default=C.VERIFY_MODE_STANDARD)
    p.set_defaults(func=_cmd_verify)

    p = sub.add_parser('enroll-face', help='录入人脸（交互式单方向）')
    p.add_argument('--name', required=True)
    p.add_argument('--admin', type=int, default=0, choices=[0, 1])
    p.add_argument('--direction', type=int, default=C.FACE_DIRECTION_MIDDLE)
    p.add_argument('--timeout', type=int, default=30)
    p.set_defaults(func=_cmd_enroll_face)

    p = sub.add_parser('enroll-palm', help='录入掌静脉')
    p.add_argument('--name', required=True)
    p.add_argument('--admin', type=int, default=0, choices=[0, 1])
    p.add_argument('--timeout', type=int, default=30)
    p.set_defaults(func=_cmd_enroll_palm)

    sub.add_parser('list', help='列出已注册用户').set_defaults(func=_cmd_list)

    p = sub.add_parser('delete', help='删除单个用户')
    p.add_argument('--user-id', type=int, required=True)
    p.add_argument('--user-type', type=int, default=C.USER_TYPE_FACE, choices=[0, 1])
    p.set_defaults(func=_cmd_delete)

    p = sub.add_parser('delete-all', help='批量删除用户')
    p.add_argument('--type', type=int, default=C.DELALL_TYPE_ALL)
    p.set_defaults(func=_cmd_delete_all)

    p = sub.add_parser('capture', help='抓拍并下载图片')
    p.add_argument('--number', type=int, default=0)
    p.add_argument('--width', type=int, default=0)
    p.add_argument('--height', type=int, default=0)
    p.add_argument('--output', '-o', default='')
    p.set_defaults(func=_cmd_capture)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    client = X2000Client(args.port, baudrate=args.baudrate, name_encoding=args.encoding)
    try:
        client.connect(wait_ready=False)
        args.func(client, args)
    except X2000Error as e:
        print('错误: %s' % e, file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
