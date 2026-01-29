import socket
import struct
import sys
import os

# --- CONFIGURATION (PULLED FROM SECRETS) ---
SERVER_IP = os.environ.get('SERVER_IP')
PORT = int(os.environ.get('SERVER_PORT'))

def check_bedrock():
    # Bedrock Unconnected Ping Packet
    ping_packet = bytearray.fromhex("01000000000000000000ffff00fefefefefdfdfdfd12345678")
    ping_packet.extend(struct.pack('>q', 0))
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0) 
    
    try:
        sock.sendto(ping_packet, (SERVER_IP, PORT))
        data, addr = sock.recvfrom(1024)
        if data:
            return "ONLINE"
    except:
        pass
    finally:
        sock.close()
    return "OFFLINE"

if __name__ == "__main__":
    result = check_bedrock()
    # Print for YAML to capture
    print(result)
    # Always exit 0 so GitHub doesn't show a Red Error
    sys.exit(0)
