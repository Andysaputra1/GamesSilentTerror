"""Socket.IO untuk chat publik realtime: server.py membuat sio dan emit_room, chat.py mendaftarkan event-nya.

Aksi, vote, dan snapshot permainan tidak lewat socket, tetapi lewat HTTP (controllers/rooms.py).
"""
