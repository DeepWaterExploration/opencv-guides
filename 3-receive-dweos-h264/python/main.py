import cv2
from rtp_receiver import RTPReceiver
from h264_decoder import H264Decoder

def main():
    # Configure to listen on 127.0.0.1:5000 as requested
    input_ip="127.0.0.1"
    input_port=5600

    receiver = RTPReceiver(ip=input_ip, port=input_port)
    decoder = H264Decoder()

    print("Listening for RTP stream on 127.0.0.1:5600...")
    print("Press 'q' to quit.")

    try:
        for nal_unit in receiver.get_nal_units():
            frames = decoder.decode(nal_unit)
            
            for frame in frames:
                cv2.imshow("RTP Stream", frame)
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    return

    except KeyboardInterrupt:
        pass
    finally:
        receiver.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
