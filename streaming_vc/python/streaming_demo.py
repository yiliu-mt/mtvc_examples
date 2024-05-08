import argparse
import time
import wave
import json
import logging
import websocket
import numpy as np
from functools import partial
from threading import Thread
from scipy.io.wavfile import write


DEFAULT_URL = 'ws://aidev.mthreads.com:45003/api/v2/vc/streaming_vc'

INPUT_SR = 16000
INPUT_CHANNELS = 1
INPUT_BITS = 16
INPUT_FORMAT = 'pcm'

OUTPUT_SR = 48000
OUTPUT_CHANNELS = 1
OUTPUT_BITS=16
OUTPUT_FORMAT = 'pcm'


def bytes_to_np_array(audio_bytes, encoding, channels):
    if encoding == "pcm":
        np_array = np.frombuffer(audio_bytes, dtype=np.int16)
    else:
        raise NotImplemented(f"Unsupported encoding : {encoding}")
    return np_array.reshape(-1, channels)


class WsClient():
    def __init__(self, args):
        self.url = args.url
        self.config_signal = {
          "type": "StartConversion",
          "payload":{
            "voice": args.voice,
            "input_info":{
              "sample_rate": INPUT_SR,
              "channels": INPUT_CHANNELS,
              "bits": INPUT_BITS,
              "audio_encoding": INPUT_FORMAT
            },
            "output_info":{
              "sample_rate": OUTPUT_SR,
              "channels": OUTPUT_CHANNELS,
              "bits": OUTPUT_BITS,
              "audio_encoding": OUTPUT_FORMAT
            }
          }
        }
        self.end_signal = {
            "type": "StopConversion"
        }
        self.ws_header = None
        if args.token is not None and len(args.token) > 0:
            if args.mode == "cloud":
                self.ws_header = {"Authorization": args.token}
            elif args.mode == "local":
                self.url = '{}?token={}'.format(self.url, args.token)

        # Log设置
        self.logger = logging.getLogger("RunLog")
        self.logger.setLevel(logging.INFO)

        self.audio_chunks = []

    def on_open(self, ws, file_path):
        def run(*args):
            with wave.open(file_path, 'rb') as wf:
                sample_rate = wf.getframerate()
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                audio_data = wf.readframes(wf.getnframes())
            assert sample_rate == INPUT_SR, f"The sample rate {sample_rate} is not supported"
            assert channels == INPUT_CHANNELS, f"The channels {channels} is not supported"
            assert sample_width == int(INPUT_BITS / 8), f"The sample width {sample_width} is not supported"

            chunk_size = 1000
            bytes_per_chunk = int(sample_rate * channels * sample_width * chunk_size / 1000.)

            # 首先发送配置
            ws.send(json.dumps(self.config_signal))

            # 流式发送数据包
            index = 0
            while index < len(audio_data):
                chunk = audio_data[index : index + bytes_per_chunk]
                # time.sleep(0.001)
                time.sleep(len(chunk) / sample_rate / channels / sample_width)
                print("send data")
                ws.send(chunk, 2)
                index += bytes_per_chunk

            # 发送尾包
            ws.send(json.dumps(self.end_signal))
        Thread(target=run).start()

    def on_message(self, ws, message):
        try:
            json_data = json.loads(message)
            if json_data['status'] != 1000:
                print(json_data)
                return
            if json_data['type'] == 'ConversionStarted':
                print("Start conversion")
            elif json_data['type'] == 'ConversionCompleted':
                print("Stop conversion")
            elif json_data['type'] == 'Error':
                print(json_data)
        except:
            print("receive converted data")
            audio_chunk = bytes_to_np_array(message, 'pcm', 1)[:, 0]
            self.audio_chunks.append(audio_chunk)

    def on_error(self, ws, error):
        print("error: ", error)

    def on_close(self, ws, close_status_code, close_msg):
        ws.close()
        print("### closed ###")

    def send(self, file_path):
        # start websocket-client
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            self.url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            header=self.ws_header,
        )
        ws.on_open = partial(self.on_open, file_path=file_path)
        ws.run_forever()
        return np.concatenate(self.audio_chunks, axis=-1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL, type=str, help="The endpoint to connect to")
    parser.add_argument("--mode", choices=["cloud", "local"], default="cloud", type=str, help="The authorization mode")
    parser.add_argument("--token", default=None, type=str, help="The authorization token")
    parser.add_argument('--voice', type=str, required=True, help='the target voice')
    parser.add_argument("--input_file", type=str, required=True, help='the path of the input WAV file')
    parser.add_argument("--output_file", type=str, required=True, help='the path of the output WAV file')
    args = parser.parse_args()
    ws_client = WsClient(args)
    audio_data = ws_client.send(args.input_file)
    write(args.output_file, OUTPUT_SR, audio_data)

