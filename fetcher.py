#!/usr/bin/env python3
import sys
import time
import json
import subprocess
import requests
import m3u8
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QTextEdit, QGroupBox,
    QScrollArea
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

fake_headers = {
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'zh,en-US;q=0.9,en;q=0.8,zh-CN;q=0.7,ja;q=0.6',
    'Accept-Charset': 'UTF-8,*;q=0.5',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
}


def parse_room_url_key(input_text):
    """从URL或直接的room_url_key中提取key"""
    input_text = input_text.strip().rstrip('/')
    # 支持 https://www.showroom-live.com/r/KEY 或 https://www.showroom-live.com/KEY
    if 'showroom-live.com' in input_text:
        parts = input_text.split('/')
        return parts[-1]
    return input_text


def get_roomid_by_room_url_key(room_url_key):
    url = "https://www.showroom-live.com/api/room/status"
    params = {"room_url_key": room_url_key}
    response = requests.get(url=url, headers=fake_headers, params=params, timeout=10)
    data = response.json()
    return data['room_id'], data.get('room_name', room_url_key), data.get('is_live', False)


def get_raw_stream_list(room_id):
    """返回 API 原始流列表"""
    api_endpoint = (
        'https://www.showroom-live.com/api/live/streaming_url'
        '?room_id={room_id}&_={timestamp}&abr_available=1'
    ).format(room_id=room_id, timestamp=str(int(time.time() * 1000)))
    response = requests.get(url=api_endpoint, headers=fake_headers, timeout=10)
    data = json.loads(response.text)
    url_list = data.get('streaming_url_list', [])
    if not url_list:
        raise Exception('No streaming URLs available (room may be offline)')
    return url_list


def expand_hls_all(m3u8_url):
    """解析 hls_all m3u8，返回 [(sort_key, label, url), ...]"""
    try:
        playlist = m3u8.load(m3u8_url)
        if not playlist.playlists:
            return [(0, 'hls_all  |  Default', m3u8_url)]
        results = []
        for p in playlist.playlists:
            bw = p.stream_info.bandwidth
            url = p.uri
            if not url.startswith('http'):
                base = m3u8_url.rsplit('/', 1)[0]
                url = f'{base}/{url}'
            parts = ['hls_all', f'{bw // 1000} kbps']
            res = p.stream_info.resolution
            if res:
                parts.append(f'{res[0]}x{res[1]}')
            fps = p.stream_info.frame_rate
            if fps:
                parts.append(f'{fps:.0f}fps')
            codecs = p.stream_info.codecs
            if codecs:
                parts.append(codecs)
            results.append((bw, '  |  '.join(parts), url))
        results.sort(key=lambda x: x[0], reverse=True)
        return results
    except Exception:
        return [(0, 'hls_all  |  Default', m3u8_url)]


def get_all_streams(url_list):
    """将 API 流列表展开为 [(sort_key, label, url), ...]，hls_all 展开子流"""
    streams = []
    for item in url_list:
        stream_type = item.get('type', 'unknown')
        url = item['url']
        quality = item.get('quality', '')
        label_parts = item.get('label', '')

        if stream_type == 'hls_all':
            streams.extend(expand_hls_all(url))
        elif stream_type == 'hls':
            parts = [stream_type]
            if quality:
                parts.append(str(quality))
            if label_parts:
                parts.append(str(label_parts))
            streams.append((-1, '  |  '.join(parts), url))
        else:
            # webrtc 等其他协议
            parts = [stream_type]
            if quality:
                parts.append(str(quality))
            if label_parts:
                parts.append(str(label_parts))
            streams.append((-2, '  |  '.join(parts), url))
    return [(label, url) for _, label, url in streams]


class FetchThread(QThread):
    log = pyqtSignal(str)
    streams_ready = pyqtSignal(list, str)  # [(label, url)], room_name
    error = pyqtSignal(str)

    def __init__(self, room_input):
        super().__init__()
        self.room_input = room_input

    def run(self):
        try:
            room_url_key = parse_room_url_key(self.room_input)
            self.log.emit(f'Room key: {room_url_key}')

            self.log.emit('Fetching room info...')
            room_id, room_name, is_live = get_roomid_by_room_url_key(room_url_key)
            self.log.emit(f'Room: {room_name} (ID: {room_id})')

            if not is_live:
                self.error.emit(f'Room "{room_name}" is currently offline.')
                return

            self.log.emit('Fetching stream list...')
            url_list = get_raw_stream_list(room_id)
            self.log.emit(f'Found {len(url_list)} raw streams')

            self.log.emit('Analyzing streams...')
            streams = get_all_streams(url_list)
            for label, url in streams:
                self.log.emit(f'  [{label}] {url}')

            self.streams_ready.emit(streams, room_name)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Showroom Fetcher')
        self.setMinimumWidth(640)
        self.streams = []
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # Input group
        input_group = QGroupBox('Room')
        input_layout = QHBoxLayout(input_group)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('room_url_key  or  https://www.showroom-live.com/r/...')
        self.url_input.returnPressed.connect(self.fetch_streams)
        self.fetch_btn = QPushButton('Fetch')
        self.fetch_btn.setFixedWidth(70)
        self.fetch_btn.clicked.connect(self.fetch_streams)
        input_layout.addWidget(self.url_input)
        input_layout.addWidget(self.fetch_btn)
        layout.addWidget(input_group)

        # Stream list
        stream_group = QGroupBox('Streams')
        stream_group_layout = QVBoxLayout(stream_group)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(160)
        self._stream_list_widget = QWidget()
        self._stream_list_layout = QVBoxLayout(self._stream_list_widget)
        self._stream_list_layout.setSpacing(4)
        self._stream_list_layout.addStretch()
        scroll.setWidget(self._stream_list_widget)
        stream_group_layout.addWidget(scroll)
        layout.addWidget(stream_group)

        # Log
        log_group = QGroupBox('Log')
        log_layout = QVBoxLayout(log_group)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont('Menlo', 11))
        self.log_view.setFixedHeight(180)
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_group)

        self.status_label = QLabel('')
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

    def _clear_stream_list(self):
        layout = self._stream_list_layout
        while layout.count() > 1:  # keep the trailing stretch
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_stream_row(self, label, url):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        lbl = QLabel(label)
        lbl.setFont(QFont('Menlo', 10))
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row_layout.addWidget(lbl, stretch=1)

        copy_btn = QPushButton('Copy URL')
        copy_btn.setFixedWidth(80)
        copy_btn.clicked.connect(lambda _, u=url: QApplication.clipboard().setText(u))
        row_layout.addWidget(copy_btn)

        vlc_btn = QPushButton('VLC')
        vlc_btn.setFixedWidth(50)
        vlc_btn.clicked.connect(lambda _, u=url: self._launch_vlc(u))
        row_layout.addWidget(vlc_btn)

        self._stream_list_layout.insertWidget(self._stream_list_layout.count() - 1, row)

    def log(self, msg):
        self.log_view.append(msg)

    def fetch_streams(self):
        room_input = self.url_input.text().strip()
        if not room_input:
            return
        self.fetch_btn.setEnabled(False)
        self._clear_stream_list()
        self.streams = []
        self.status_label.setText('Fetching...')
        self.log_view.clear()

        self._thread = FetchThread(room_input)
        self._thread.log.connect(self.log)
        self._thread.streams_ready.connect(self.on_streams_ready)
        self._thread.error.connect(self.on_error)
        self._thread.finished.connect(lambda: self.fetch_btn.setEnabled(True))
        self._thread.start()

    def on_streams_ready(self, streams, room_name):
        self.streams = streams
        self._clear_stream_list()
        for label, url in streams:
            self._add_stream_row(label, url)
        self.status_label.setText(f'Ready: {room_name}  ({len(streams)} streams)')

    def on_error(self, msg):
        self.log(f'Error: {msg}')
        self.status_label.setText(f'Error: {msg}')

    def _launch_vlc(self, url):
        self.log(f'Launching VLC: {url}')
        vlc_paths = [
            'vlc',
            '/Applications/VLC.app/Contents/MacOS/VLC',
            '/usr/bin/vlc',
            '/usr/local/bin/vlc',
        ]
        for path in vlc_paths:
            try:
                subprocess.Popen([path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.status_label.setText('VLC launched.')
                return
            except FileNotFoundError:
                continue
        self.on_error('VLC not found. Please install VLC or add it to PATH.')


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
