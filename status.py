import socket
import struct
import sys
import os

SERVER_IP = os.environ.get('SERVER_IP')
PORT = int(os.environ.get('SERVER_PORT'))

def check_bedrock():
    ping_packet = bytearray.fromhex("01000000000000000000ffff00fefefefefdfdfdfd12345678")
    ping_packet.extend(struct.pack('>q', 0))
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0) 
    
    try:
        sock.sendto(ping_packet, (SERVER_IP, PORT))
        data, addr = sock.recvfrom(1024)
        if data:
            return "Online"
    except:
        pass
    finally:
        sock.close()
    return "Offline"

if __name__ == "__main__":
    result = check_bedrock()
    print("🟢 Server is Online. Stopping." if result == "Online" else "🔴 Server is Offline. Continuing...")
    sys.exit(0)
