import argparse
import time
import grpc
import wave
import numpy as np
from scipy.io.wavfile import write
from proto import service_pb2, service_pb2_grpc


input_sample_rate = 16000
output_sample_rate = 48000


def bytes_to_np_array(audio_bytes, encoding, channels):
    '''Convert audio bytes to numpy array

    Args:
      encoding: enum options: pcm
      channels: the num of channels
    '''
    if encoding == "pcm":
        np_array = np.frombuffer(audio_bytes, dtype=np.int16)
    else:
        raise NotImplemented(f"Unsupported encoding : {encoding}")
    return np_array.reshape(-1, channels)


def load_wav_file(filename):
    """
    Load a WAV file and return its raw PCM data, sample rate, number of channels, and sample width.
    """
    with wave.open(filename, 'rb') as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        audio_data = wf.readframes(wf.getnframes())
    
    return audio_data, sample_rate, channels, sample_width


def request_generator(target_voice, input_audio_path, chunk_size, simulate_delay):
    '''generator to send the gRPC request
    '''
    audio_data, sample_rate, channels, sample_width = load_wav_file(input_audio_path)
    assert sample_rate == input_sample_rate, f"The sample rate {sample_rate} is not supported"
    assert channels == 1, f"The channels {channels} is not supported"
    assert sample_width == 2, f"The sample width {sample_width} is not supported"

    # Send VoiceConversionConfig first
    config = service_pb2.VoiceConversionConfig(
        type="StartConversion",
        payload=service_pb2.VoiceConversionConfig.Payload(
            voice=target_voice,
            input_info=service_pb2.VoiceConversionConfig.AudioInfo(
                sample_rate=input_sample_rate,
                channels=1,
                bits=16,
                audio_encoding="pcm"
            ),
            output_info=service_pb2.VoiceConversionConfig.AudioInfo(
                sample_rate=output_sample_rate,
                channels=1,
                bits=16,
                audio_encoding="pcm"
            )
        )
    )
    print("sending config...")
    yield service_pb2.StreamingVCRequest(config=config)

    # Stream audio data
    bytes_per_chunk = int(sample_rate * channels * sample_width * chunk_size / 1000.)
    for i in range(0, len(audio_data), bytes_per_chunk):
        chunk = audio_data[i:i + bytes_per_chunk]
        if simulate_delay:
            delay_time = len(chunk) / sample_rate / sample_width
            time.sleep(delay_time)
        print("sending audio data...")
        yield service_pb2.StreamingVCRequest(audio_data=chunk)

    config = service_pb2.VoiceConversionConfig(type="StopConversion")
    yield service_pb2.StreamingVCRequest(config=config)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--hostname', type=str, default='127.0.0.1', help='hostname')
    parser.add_argument('--port', type=int, default=50051, help='port')
    parser.add_argument('--voice', type=str, required=True, help='the target voice')
    parser.add_argument("--simulate_delay", type=lambda x: (str(x).lower() == 'true'), default=False, help="Whether to delay between packets")
    parser.add_argument('--chunk_size', type=int, default=1000, help='the chunk size for each package (in ms)')
    parser.add_argument("--input_wav", type=str, required=True, help='the path of the input WAV file')
    parser.add_argument("--output_wav", type=str, required=True, help='the path of the output WAV file')
    args = parser.parse_args()

    channel = grpc.insecure_channel('{}:{}'.format(args.hostname, args.port))
    stub = service_pb2_grpc.VoiceConversionStub(channel)

    responses = stub.StreamingVC(request_generator(args.voice, args.input_wav, args.chunk_size, args.simulate_delay))
    audio_chunks = []
    for response in responses:
        if response.HasField("state"):
            if response.state.type == "Error" or response.state.status != 1000:
                raise RuntimeError("Error occurs: {}".format(response.state.status_text))
            elif response.state.type == "ConversionStarted":
                print("Conversion started")
            elif response.state.type == "ConversionCompleted":
                print("Conversion completed")
        else:
            audio_chunk = bytes_to_np_array(response.audio_data, 'pcm', 1)[:, 0]
            audio_chunks.append(audio_chunk)
    
    audio = np.concatenate(audio_chunks, axis=-1)
    write(args.output_wav, output_sample_rate, audio)
