import socket
import struct
import argparse
import os
import time
import threading

# Constants
HEADER_FORMAT = '!HHHH'  # Sequence, Acknowledgment, Flags, Receiver Window
HEADER_SIZE = 8
CHUNK_SIZE = 992  # Data size per packet
TIMEOUT = 0.4  # seconds

# Flag values
FLAG_SYN = 0b0010
FLAG_ACK = 0b0001
FLAG_FIN = 0b1000
FLAG_RST = 0b0000  # Unused in this implementation

def create_packet(seq, ack, flags, rwnd, data=b''):
    header = struct.pack(HEADER_FORMAT, seq, ack, flags, rwnd)
    return header + data

def parse_packet(packet):
    header = packet[:HEADER_SIZE]
    data = packet[HEADER_SIZE:]
    seq, ack, flags, rwnd = struct.unpack(HEADER_FORMAT, header)
    return seq, ack, flags, rwnd, data

def server(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ip, port))

    print(f"Server listening on {ip}:{port}")
    sock.settimeout(None)

    while True:
        data, addr = sock.recvfrom(1024)
        seq, ack, flags, rwnd, _ = parse_packet(data)

        if flags & FLAG_SYN:
            print("Received SYN")
            syn_ack = create_packet(0, seq + 1, FLAG_SYN | FLAG_ACK, 15)
            sock.sendto(syn_ack, addr)
            print("Sent SYN-ACK")
        elif flags & FLAG_FIN:
            print("Received FIN")
            fin_ack = create_packet(0, seq + 1, FLAG_FIN | FLAG_ACK, 0)
            sock.sendto(fin_ack, addr)
            print("Sent FIN-ACK")
        elif flags & FLAG_ACK:
            print(f"Received ACK: {ack}")
        elif len(data) > HEADER_SIZE:
            print(f"Received data chunk, seq {seq}")
            ack_pkt = create_packet(0, seq + 1, FLAG_ACK, 15)
            sock.sendto(ack_pkt, addr)

def client(ip, port, filename, window_size):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)
    server_address = (ip, port)

    # 3-Way Handshake
    syn_pkt = create_packet(0, 0, FLAG_SYN, 0)
    sock.sendto(syn_pkt, server_address)
    print("Sent SYN")

    try:
        data, _ = sock.recvfrom(1024)
    except socket.timeout:
        print("Timeout waiting for SYN-ACK")
        return

    _, ack, flags, recv_window, _ = parse_packet(data)
    if flags & FLAG_ACK and flags & FLAG_SYN:
        print("Received SYN-ACK")
        real_window = min(window_size, recv_window)
        ack_pkt = create_packet(0, ack, FLAG_ACK, 0)
        sock.sendto(ack_pkt, server_address)
        print(f"Sent ACK. Using window size: {real_window}")
    else:
        print("Invalid SYN-ACK")
        return

    # File transfer
    if not os.path.exists(filename):
        print("File not found")
        return

    with open(filename, 'rb') as f:
        chunks = []
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)

    base = 0
    next_seq = 0
    total_packets = len(chunks)
    start_time = time.time()

    acked = [False] * total_packets

    while base < total_packets:
        # Send packets in window
        while next_seq < base + real_window and next_seq < total_packets:
            pkt = create_packet(next_seq, 0, 0, 0, chunks[next_seq])
            sock.sendto(pkt, server_address)
            print(f"Sent packet seq={next_seq}")
            next_seq += 1

        # Wait for ACK
        try:
            data, _ = sock.recvfrom(1024)
            _, ack, flags, _, _ = parse_packet(data)
            if flags & FLAG_ACK:
                print(f"Received ACK for seq={ack-1}")
                base = ack
        except socket.timeout:
            print("Timeout. Resending window...")
            next_seq = base

    # FIN phase
    fin_pkt = create_packet(0, 0, FLAG_FIN, 0)
    sock.sendto(fin_pkt, server_address)
    print("Sent FIN")

    try:
        data, _ = sock.recvfrom(1024)
        _, ack, flags, _, _ = parse_packet(data)
        if flags & FLAG_ACK and flags & FLAG_FIN:
            print("Received FIN-ACK. Connection closed.")
    except socket.timeout:
        print("No FIN-ACK received.")

    end_time = time.time()
    duration = end_time - start_time
    size_bytes = os.path.getsize(filename)
    throughput = (size_bytes * 8) / (duration * 1_000_000)  # Mbps
    print(f"Throughput: {throughput:.2f} Mbps")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', action='store_true', help='Run as server')
    parser.add_argument('-c', action='store_true', help='Run as client')
    parser.add_argument('-i', type=str, required=True, help='IP address')
    parser.add_argument('-p', type=int, required=True, help='Port')
    parser.add_argument('-f', type=str, help='Filename to transfer (client only)')
    parser.add_argument('-w', type=int, default=3, help='Window size (client only)')

    args = parser.parse_args()

    if args.s:
        server(args.i, args.p)
    elif args.c:
        client(args.i, args.p, args.f, args.w)
    else:
        print("Specify either -s (server) or -c (client)")

if __name__ == '__main__':
    main()
