from pathlib import Path
from datetime import datetime
import time
import shutil
import os
import threading
import glob
import ctypes
import psutil

import win32gui
import win32process

import cv2
import numpy as np
from mss import mss

import watchdog.observers
import watchdog.events

import global_hotkeys as ghk



# set profile number here
PROFILE_NUMBER = 1

# set count backups
BACKUP_COUNT = 15

# binding hotkeys
bindings = [
    [['f1' ], 'toggle_ignore_events'],  # toggles observation for changing save files
    [['f9' ], 'restore_backup1'],       # restore last backup
    [['f10'], 'restore_backup2'],       # restore penultimate backup
    [['f11'], 'restore_backup3'],       # penultimate - 1
]

# large screenshots will be scaled down to this size in width
MAX_IMAGE_WIDTH = 1200



def get_last_number_for_path(path, remove_old = False):
    files = os.listdir(path)
    paths = sorted([os.path.join(path, basename) for basename in files], key=os.path.getctime)
    if remove_old:
        for adir in paths[:-BACKUP_COUNT]:
            shutil.rmtree(adir)
    if len(paths) == 0:
        return 0
    else:
        return int(os.path.basename(max(paths[-BACKUP_COUNT:], key=os.path.getctime)))


def log(str):
    print(datetime.now().strftime('%H:%M:%S.%f')[:-3] + ' - ' + str)

class WindowFind:
    # EnumWindows = ctypes.windll.user32.EnumWindows
    _EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
    _GetWindowText = ctypes.windll.user32.GetWindowTextW
    _GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
    _IsWindowVisible = ctypes.windll.user32.IsWindowVisible
    _process_name = ''

    def __init__(self, process_name):
      self._process_name = str(process_name).lower()

    def getProcessIDByName(self):
        if self._process_name == '':
            return None
        pids = []
        for proc in psutil.process_iter():
            if self._process_name in proc.name().lower():
                pids.append(proc.pid)
        return pids

    def get_hwnds_for_pid(self, pid):
        def callback(hwnd, hwnds):
            found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in found_pid:
                hwnds.append(hwnd)
            return True
        hwnds = []
        win32gui.EnumWindows(callback, hwnds)
        return hwnds

    def get_rect(self, hwnd):
        rect = {'top': 0, 'left': 0, 'width': 0, 'height': 0};
        if hwnd is None or hwnd == 0:
            return rect
        try:
            rect = win32gui.GetWindowRect(hwnd)
        except Exception as exc:
            log(f'Dont get window rect by hwnd={hwnd}. Error: {str(exc)}')
            return rect
        return {'top': rect[0], 'left': rect[1], 'width': rect[2], 'height': rect[3]}

    def getWindowTitleByHandle(self, hwnd):
        length = self._GetWindowTextLength(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        self._GetWindowText(hwnd, buff, length + 1)
        return buff.value

    def getHandle(self):
        pids = self.getProcessIDByName()
        for i in pids:
            hwnds = self.get_hwnds_for_pid(i)
            for hwnd in hwnds:
                if self._IsWindowVisible(hwnd):
                    return hwnd


class WatchFilesChangeHandler(watchdog.events.PatternMatchingEventHandler):
    _src_dir = ''
    _dst_dir = ''
    _file_cache = {}
    _modifyCallback = None
    ignore_events = False

    def __init__(self, modifyCallback):
        watchdog.events.PatternMatchingEventHandler.__init__(
            self, patterns=['sav.dat'], ignore_directories=True, case_sensitive=False)
        self._modifyCallback = modifyCallback

    def set_paths(self, src, dst):
        self._src_dir = src
        self._dst_dir = dst

    def copy_backup(self):
        last_dir = get_last_number_for_path(self._dst_dir, True) + 1
        log(f'Backup files to dir {last_dir} from {self._src_dir}')
        loc_path = self._dst_dir + f'\\{last_dir}'
        self._modifyCallback(self._src_dir, loc_path)
        self._file_cache = {}

    def on_modified(self, event):
        if self.ignore_events:
            return
        key = (event.src_path)
        if key in self._file_cache:
            return
        log(f'Have changed files in {event.src_path}')
        self._file_cache[key] = True
        threading.Timer(5, lambda: self.copy_backup()).start()


def copy_backup_proc(from_dir, to_dir):
    global proc_hwnd
    shutil.copytree(from_dir, to_dir)

    if proc_hwnd is None or proc_hwnd == 0:
        proc_hwnd = window.getHandle()
    log(f'Found game process hwnd = {proc_hwnd}')
    if proc_hwnd is None or proc_hwnd == 0:
        return
    mon = window.get_rect(proc_hwnd)
    log(f'Game window rect = {mon}')
    if mon['width'] == 0:
      proc_hwnd = 0
      return
    with mss() as sct:
        img = sct.grab(mon)
        (w, h) = img.size[:2]
        if w > MAX_IMAGE_WIDTH:
            img = cv2.resize(np.array(img), (MAX_IMAGE_WIDTH, int(h * (MAX_IMAGE_WIDTH / float(w)))), interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(to_dir + '\\image.jpg', np.array(img), [cv2.IMWRITE_JPEG_QUALITY, 80])
        log(f'  take sreenshot and save to file {to_dir}\\image.jpg')


def restore_backup(backup_step):
    log('Press key for restore backup. Step - ' + str(backup_step))
    restore_path = dst_path + '\\' + str(get_last_number_for_path(dst_path, False) - backup_step)
    if not os.path.exists(restore_path):
        log('  recoverable path not found')
        return
    log('  restore from ' + restore_path)
    tmp_ignr_evn = event_handler.ignore_events
    event_handler.ignore_events = True
    try:
        for f in glob.glob(restore_path + '\\sav*'):
            shutil.copy2(f, src_path)
    finally:
        event_handler.ignore_events = tmp_ignr_evn

def restore_backup1():
    restore_backup(0)
def restore_backup2():
    restore_backup(1)
def restore_backup3():
    restore_backup(2)

def toggle_ignore_events():
    event_handler.ignore_events = not event_handler.ignore_events
    if event_handler.ignore_events:
        log('Disable watch for changing save files')
    else:
        log('Enable watch for changing save files')


log('Darkwood save backupper')
log('Start')

prog_path = os.path.expandvars(r'%APPDATA%\..\LocalLow\Acid Wizard Studio\Darkwood')
src_path = prog_path + f'\\prof{PROFILE_NUMBER}'
dst_path = prog_path + f'\\backup_prof{PROFILE_NUMBER}'
Path(dst_path).mkdir(parents=True, exist_ok=True)

window = WindowFind('Darkwood.exe')
proc_hwnd = window.getHandle()

event_handler = WatchFilesChangeHandler(copy_backup_proc)
event_handler.set_paths(src_path, dst_path)
observer = watchdog.observers.Observer()
observer.schedule(event_handler, path=src_path, recursive=True)
observer.start()

for i, elm in enumerate(bindings):
    bindings[i] = [elm[0], None, locals().get(str(elm[1]))]
ghk.register_hotkeys(bindings)
ghk.start_checking_hotkeys()

try:
    while True:
        time.sleep(100)
except KeyboardInterrupt:
    observer.stop()
observer.join()
ghk.remove_hotkeys(bindings)

log('Stop')
