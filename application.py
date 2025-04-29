import argparse
import socket
import sys
import time
import os
import struct
from datetime import datetime  # Add this at the top of your file
# Constants
TIMEOUT = 0.4       # Timeout for waiting ACKs (seconds)
FLAG_ACK = 0b0001
FLAG_SYN = 0b0010
FLAG_FIN = 0b0100
BUFFER_SIZE = 1000  # 8-byte header + 992 bytes data

def log(message):
    # Timestamp with microseconds
    now = datetime.now().strftime('%H:%M:%S.%f')[:-3]  # Millisecond precision
    print(f"{now} -- {message}")
def create_packet(seq_num, ack_num, flags, recv_window, data=b''):
    #Create a DRTP packet with a header and optional data payload
    header = struct.pack('!HHHH', seq_num, ack_num, flags, recv_window)
    return header + data

def parse_packet(packet):
    # Extract DRTP fields from the received packet
    header = packet[:8]
    data = packet[8:]
    seq_num, ack_num, flags, recv_window = struct.unpack('!HHHH', header)
    return seq_num, ack_num, flags, recv_window, data

# --- SERVER ---
def server(ip, port):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((ip, port))
    log(f"Listening on {ip}:{port}")

    data, client_address = server_socket.recvfrom(BUFFER_SIZE)
    seq, ack, flags, recv_window, _ = parse_packet(data)
    if flags & FLAG_SYN:
        log("SYN packet is received")
        server_socket.sendto(create_packet(0, 0, FLAG_SYN | FLAG_ACK, 15), client_address)
        log("SYN-ACK packet is sent")
        data, _ = server_socket.recvfrom(BUFFER_SIZE)
        ack_seq, ack_ack, ack_flags, _, _ = parse_packet(data)
        if ack_flags & FLAG_ACK:
            log("ACK packet is received")
            log("Connection established")
            print("\nData Transfer:\n")
            start_time = time.time()
        else:
            log("Invalid ACK, closing connection.")
            return
    else:
        log("Expected SYN, received unexpected packet.")
        return

    filename = f"received_file_{int(time.time())}"
    with open(filename, 'wb') as f:
        while True:
            try:
                packet, client_address = server_socket.recvfrom(BUFFER_SIZE)
                seq, ack, flags, recv_window, data = parse_packet(packet)

                if flags & FLAG_FIN:
                    print("\nConnection Teardown:\n")
                    log("FIN packet is received")
                    server_socket.sendto(create_packet(0, 0, FLAG_FIN | FLAG_ACK, 0), client_address)
                    log("FIN ACK packet is sent")
                    break

                log(f"packet {seq} is received")
                log(f"sending ack for the received {seq}")
                server_socket.sendto(create_packet(0, seq, FLAG_ACK, 0), client_address)
                f.write(data)

            except socket.timeout:
                log("Timeout waiting for data.")
                break

    end_time = time.time()
    throughput_mbps = calculate_throughput(filename, start_time, end_time)
    log(f"The throughput is {throughput_mbps:.2f} Mbps")
    log("Connection closes")
    server_socket.close()

def calculate_throughput(filename, start_time, end_time):
    elapsed_time = end_time - start_time
    file_size_bytes = os.path.getsize(filename)
    return (file_size_bytes * 8) / (elapsed_time * 1_000_000)

# --- CLIENT ---
def client(ip, port, filename, window_size):
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.settimeout(TIMEOUT)
    server_address = (ip, port)

    print("\nConnection Establishment Phase:\n")
    client_socket.sendto(create_packet(0, 0, FLAG_SYN, window_size), server_address)
    log("SYN packet is sent")

    data, _ = client_socket.recvfrom(BUFFER_SIZE)
    seq, ack, flags, recv_window, _ = parse_packet(data)
    if flags & FLAG_SYN and flags & FLAG_ACK:
        log("SYN-ACK packet is received")
        client_socket.sendto(create_packet(1, 0, FLAG_ACK, window_size), server_address)
        log("ACK packet is sent")
        log("Connection established")
    else:
        log("Unexpected packet in handshake")
        return

    print("\nData Transfer:\n")
    with open(filename, 'rb') as f:
        chunks = []
        while chunk := f.read(992):
            chunks.append(chunk)

    base = 0
    next_seq = 0
    total = len(chunks)
    start_time = time.time()

    while base < total:
        while next_seq < base + window_size and next_seq < total:
            pkt = create_packet(next_seq, 0, 0, window_size, chunks[next_seq])
            client_socket.sendto(pkt, server_address)
            log(f"packet with seq = {next_seq} is sent, sliding window = {{{', '.join(str(i) for i in range(base, next_seq + 1))}}}")
            next_seq += 1

        try:
            ack_pkt, _ = client_socket.recvfrom(BUFFER_SIZE)
            _, ack_num, flags, _, _ = parse_packet(ack_pkt)
            if flags & FLAG_ACK:
                log(f"ACK for packet = {ack_num} is received")
                base = ack_num + 1
        except socket.timeout:
            log("Timeout! Resending from base...")
            next_seq = base

    print("\nConnection Teardown:\n")
    client_socket.sendto(create_packet(0, 0, FLAG_FIN, window_size), server_address)
    log("FIN packet is sent")

    data, _ = client_socket.recvfrom(BUFFER_SIZE)
    _, _, flags, _, _ = parse_packet(data)
    if flags & FLAG_ACK and flags & FLAG_FIN:
        log("FIN-ACK packet is received")
        log("Connection closes")

    end_time = time.time()
    file_size_bytes = os.path.getsize(filename)
    throughput_mbps = (file_size_bytes * 8) / (end_time - start_time) / 1_000_000
    log(f"The throughput is {throughput_mbps:.2f} Mbps")
    client_socket.close()

# --- MAIN ---
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', action='store_true', help="Run as client")
    parser.add_argument('-s', action='store_true', help="Run as server")
    parser.add_argument('-i', type=str, required=True, help="IP address")
    parser.add_argument('-p', type=int, required=True, help="Port number")
    parser.add_argument('-f', type=str, help="Filename to send (client only)")
    parser.add_argument('-w', type=int, default=3, help="Window size (default 3)")

    args = parser.parse_args()
    if args.s:
        server(args.i, args.p)
    elif args.c:
        if not args.f:
            print("[ERROR] Client mode requires a filename (-f)")
            sys.exit(1)
        client(args.i, args.p, args.f, args.w)
    else:
        print("[ERROR] Please specify a mode: -c (client) or -s (server)")
        sys.exit(1)

if __name__ == "__main__":
    main()
