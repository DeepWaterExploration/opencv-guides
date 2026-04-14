import socket
import threading
import queue

class RTPReceiver:
    def __init__(self, ip="127.0.0.1", port=5000):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Increase receive buffer to 16MB for high-bitrate 1080p
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024)
        except Exception as e:
            print(f"Warning: Could not increase UDP buffer size: {e}")

        self.sock.bind((self.ip, self.port))
        self.sock.settimeout(1.0)
        
        # This queue will now hold complete NAL units, not raw packets
        self.nal_queue = queue.Queue(maxsize=500)
        self.running = True
        self.worker = threading.Thread(target=self._receive_loop, daemon=True)
        self.worker.start()
        
        self.buffer = bytearray()
        self.last_seq = -1

    def _receive_loop(self):
        """Background thread to drain the UDP socket and reassemble NAL units."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(2048)
                if len(data) < 12:
                    continue
                
                seq = (data[2] << 8) | data[3]
                if self.last_seq != -1:
                    expected = (self.last_seq + 1) & 0xFFFF
                    if seq != expected:
                        gap = (seq - expected) & 0xFFFF
                        if gap > 1:
                            print(f"Packet loss: dropped {gap} packets")
                        self.buffer = bytearray()
                
                self.last_seq = seq
                payload = data[12:]
                if not payload:
                    continue

                nal_header = payload[0]
                nal_type = nal_header & 0x1F
                
                if nal_type == 28: # FU-A
                    if len(payload) < 2:
                        continue
                    fu_header = payload[1]
                    start_bit = fu_header & 0x80
                    end_bit = fu_header & 0x40
                    
                    if start_bit:
                        reconstructed_header = (nal_header & 0xE0) | (fu_header & 0x1F)
                        self.buffer = bytearray([reconstructed_header])
                        self.buffer.extend(payload[2:])
                    elif len(self.buffer) > 0:
                        self.buffer.extend(payload[2:])
                    
                    if end_bit and len(self.buffer) > 0:
                        self._put_nal(bytes(self.buffer))
                        self.buffer = bytearray()

                elif nal_type == 24: # STAP-A
                    offset = 1
                    try:
                        while offset + 2 <= len(payload):
                            size = (payload[offset] << 8) | payload[offset + 1]
                            offset += 2
                            if offset + size <= len(payload):
                                self._put_nal(payload[offset : offset + size])
                            offset += size
                    except Exception:
                        pass
                else:
                    self._put_nal(payload)

            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Receiver error: {e}")
                break

    def _put_nal(self, nal):
        try:
            self.nal_queue.put_nowait(nal)
        except queue.Full:
            try:
                self.nal_queue.get_nowait()
                self.nal_queue.put_nowait(nal)
            except queue.Empty:
                pass

    def get_nal_units(self):
        """Generator that pulls complete NAL units from the background thread."""
        while self.running:
            try:
                yield self.nal_queue.get(timeout=1.0)
            except queue.Empty:
                continue

    def close(self):
        self.running = False
        self.sock.close()
