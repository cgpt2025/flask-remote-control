from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
import time
import threading
import csv
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import hashlib

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

# Configuration
COMPUTERS = [
    '192.168.29.59',
    '10.133.115.51', 
    '10.133.115.52',
    '10.133.115.53'
]
FILE_PATH = 'D:\\note.txt'
REFRESH_INTERVAL = 2  # seconds - easily changeable
CHAT_STORAGE_DIR = 'chat_history'
FILE_HASHES = {}   # {ip: file_hash}

# Create chat storage directory
os.makedirs(CHAT_STORAGE_DIR, exist_ok=True)

def get_chat_file_path(ip):
    """Get the CSV file path for a specific IP"""
    return os.path.join(CHAT_STORAGE_DIR, f"chat_{ip.replace('.', '_')}.csv")

def initialize_chat_file(ip):
    """Initialize CSV file with headers if it doesn't exist"""
    chat_file = get_chat_file_path(ip)
    if not os.path.exists(chat_file):
        with open(chat_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'type', 'content', 'datetime'])

def add_message_to_chat(ip, message_type, content):
    """Add a message to the chat history CSV file"""
    chat_file = get_chat_file_path(ip)
    timestamp = datetime.now().strftime('%H:%M')
    full_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Initialize file if it doesn't exist
    initialize_chat_file(ip)
    
    with open(chat_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, message_type, content, full_datetime])

def get_chat_history(ip):
    """Read chat history from CSV file"""
    chat_file = get_chat_file_path(ip)
    messages = []
    
    if os.path.exists(chat_file):
        try:
            with open(chat_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    messages.append({
                        'timestamp': row['timestamp'],
                        'type': row['type'],
                        'content': row['content']
                    })
        except Exception as e:
            print(f"Error reading chat history for {ip}: {e}")
    
    return messages

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, ip_address):
        self.ip_address = ip_address
        
    def on_modified(self, event):
        if event.is_directory:
            return
            
        if event.src_path.endswith('note.txt'):
            # Small delay to ensure file is fully written
            time.sleep(0.1)
            self.handle_file_change()
    
    def handle_file_change(self):
        try:
            file_path = f"\\\\{self.ip_address}\\d$\\note.txt"
            
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                
                # Calculate file hash to detect actual changes
                content_hash = hashlib.md5(content.encode()).hexdigest()
                
                if self.ip_address not in FILE_HASHES or FILE_HASHES[self.ip_address] != content_hash:
                    FILE_HASHES[self.ip_address] = content_hash
                    
                    if content:  # Only log if there's content
                        # Add as received message to CSV
                        add_message_to_chat(self.ip_address, 'received', content)
                        print(f"Received message from {self.ip_address}: {content[:50]}...")
                            
        except Exception as e:
            print(f"Error handling file change for {self.ip_address}: {e}")

def start_file_monitoring():
    """Start monitoring files on all computers"""
    observers = []
    
    for ip in COMPUTERS:
        try:
            # Try to access the remote path
            remote_path = f"\\\\{ip}\\d$"
            
            if os.path.exists(remote_path):
                observer = Observer()
                handler = FileChangeHandler(ip)
                observer.schedule(handler, remote_path, recursive=False)
                observer.start()
                observers.append(observer)
                print(f"Started monitoring {ip}")
                
                # Initialize file hash and chat file
                initialize_chat_file(ip)
                file_path = f"\\\\{ip}\\d$\\note.txt"
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    FILE_HASHES[ip] = hashlib.md5(content.encode()).hexdigest()
                    
            else:
                print(f"Cannot access {ip} - path does not exist or no permission")
                    
        except Exception as e:
            print(f"Could not monitor {ip}: {e}")
    
    return observers

@app.route('/')
def login():
    return render_template('login.html')

@app.route('/authenticate', methods=['POST'])
def authenticate():
    username = request.form.get('username')
    password = request.form.get('password')
    
    if username == 'admin' and password == 'admin':
        session['authenticated'] = True
        return redirect(url_for('select_ip'))
    else:
        return render_template('login.html', error='Invalid credentials')

@app.route('/select-ip')
def select_ip():
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    return render_template('select_ip.html')

@app.route('/chat/<ip>')
def chat(ip):
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    
    # Validate IP format (basic check)
    if not ip.replace('.', '').replace('_', '').isdigit():
        return redirect(url_for('select_ip'))
    
    # Initialize chat file for this IP
    initialize_chat_file(ip)
    
    return render_template('chat.html', ip_address=ip, refresh_interval=REFRESH_INTERVAL * 1000)

@app.route('/api/send-message', methods=['POST'])
def send_message():
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.json
    ip_address = data.get('ip')
    message = data.get('message')
    
    if not ip_address or not message:
        return jsonify({'error': 'Invalid data'}), 400
    
    try:
        # Write to the remote file
        file_path = f"\\\\{ip_address}\\d$\\note.txt"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(message)
        
        # Add to chat history as sent message
        add_message_to_chat(ip_address, 'sent', message)
        
        # Update file hash to prevent treating our own write as a received message
        FILE_HASHES[ip_address] = hashlib.md5(message.encode()).hexdigest()
        
        print(f"Sent message to {ip_address}: {message[:50]}...")
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error sending message to {ip_address}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-messages/<ip>')
def get_messages(ip):
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        messages = get_chat_history(ip)
        return jsonify({'messages': messages})
    except Exception as e:
        print(f"Error getting messages for {ip}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear-chat/<ip>', methods=['POST'])
def clear_chat(ip):
    """Clear chat history for a specific IP"""
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        chat_file = get_chat_file_path(ip)
        if os.path.exists(chat_file):
            os.remove(chat_file)
        initialize_chat_file(ip)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/system-status')
def system_status():
    """Get system status information"""
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    status = {
        'monitored_computers': [],
        'refresh_interval': REFRESH_INTERVAL
    }
    
    for ip in COMPUTERS:
        remote_path = f"\\\\{ip}\\d$"
        accessible = os.path.exists(remote_path)
        
        chat_file = get_chat_file_path(ip)
        message_count = 0
        if os.path.exists(chat_file):
            try:
                with open(chat_file, 'r', encoding='utf-8') as f:
                    message_count = sum(1 for line in f) - 1  # Subtract header row
            except:
                message_count = 0
        
        status['monitored_computers'].append({
            'ip': ip,
            'accessible': accessible,
            'message_count': message_count
        })
    
    return jsonify(status)

if __name__ == '__main__':
    print("Network Chat System Starting...")
    print(f"Refresh interval: {REFRESH_INTERVAL} seconds")
    print(f"Chat storage directory: {CHAT_STORAGE_DIR}")
    print(f"Monitoring computers: {', '.join(COMPUTERS)}")
    
    # Start file monitoring in a separate thread
    monitoring_thread = threading.Thread(target=start_file_monitoring, daemon=True)
    monitoring_thread.start()
    
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    print("Make sure to install required packages: pip install flask watchdog")
    print("Starting Flask application on http://localhost:5000")
    
    app.run(host='0.0.0.0', port=5000, debug=False)