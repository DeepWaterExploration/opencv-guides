import av
import numpy as np

class H264Decoder:
    def __init__(self):
        self.codec = av.CodecContext.create('h264', 'r')
        # SLICE threading is faster for low-latency 1080p
        self.codec.thread_type = 'SLICE'
        self.codec.thread_count = 0 # Auto
        # Correctly set low_delay flag
        self.codec.flags |= 0x1000 # AV_CODEC_FLAG_LOW_DELAY
        
        self.first_frame = True

    def decode(self, nal_unit):
        # Add Annex B start code
        packet_data = b'\x00\x00\x00\x01' + nal_unit
        packet = av.Packet(packet_data)
        
        frames_out = []
        try:
            frames = self.codec.decode(packet)
            for frame in frames:
                if self.first_frame:
                    print(f"Stream detected: {frame.width}x{frame.height} format={frame.format.name}")
                    self.first_frame = False
                
                # Robust conversion to BGR24 for OpenCV
                # For 10-bit sources, PyAV handles the bit-depth downsampling here
                img = frame.to_ndarray(format='bgr24')
                frames_out.append(img)
        except Exception as e:
            pass
            
        return frames_out
