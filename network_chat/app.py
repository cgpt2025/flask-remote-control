from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
import time
import threading
import csv
import subprocess
import requests
import json
import base64
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import hashlib

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

# Configuration
COMPUTERS = [
    '10.133.115.64',
    '10.133.115.50', 
    '10.133.115.96',
    '10.133.115.53'
]
FILE_PATH = 'D:\\note.txt'
REFRESH_INTERVAL = 2  # seconds - easily changeable
CHAT_STORAGE_DIR = 'chat_history'
FILE_HASHES = {}   # {ip: file_hash}

# GitHub config
GITHUB_TOKEN = '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'
GITHUB_API_URL = 'https://api.github.com/repos/cgpt2025/flask-remote-control/contents/ngrok_url.txt'
HEADERS = {'Authorization': f'token {GITHUB_TOKEN}'}

# Ngrok process
ngrok_process = None
public_url = None

# Create chat storage directory
os.makedirs(CHAT_STORAGE_DIR, exist_ok=True)

def update_github_url(url):
    """Update the ngrok URL in GitHub repository"""
    try:
        # First, get the current file to get its SHA (required for updates)
        response = requests.get(GITHUB_API_URL, headers=HEADERS)
        
        if response.status_code == 200:
            # File exists, get its SHA for update
            file_data = response.json()
            sha = file_data['sha']
            
            # Prepare the new content
            #content = f"Network Chat System URL: {url}\nLast updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            content = f"{url}"
            encoded_content = base64.b64encode(content.encode()).decode()
            
            # Update the file
            update_data = {
                'message': f'Update ngrok URL - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                'content': encoded_content,
                'sha': sha
            }
            
            update_response = requests.put(GITHUB_API_URL, headers=HEADERS, json=update_data)
            
        elif response.status_code == 404:
            # File doesn't exist, create it
            content = f"{url}"
            encoded_content = base64.b64encode(content.encode()).decode()
            
            create_data = {
                'message': f'Create ngrok URL file - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                'content': encoded_content
            }
            
            update_response = requests.put(GITHUB_API_URL, headers=HEADERS, json=create_data)
        
        else:
            print(f"Error accessing GitHub: {response.status_code}")
            return False
        
        if update_response.status_code in [200, 201]:
            print(f"✅ GitHub URL updated successfully: {url}")
            return True
        else:
            print(f"❌ Failed to update GitHub: {update_response.status_code}")
            print(f"Response: {update_response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error updating GitHub URL: {e}")
        return False

def start_ngrok():
    """Start ngrok tunnel and get public URL"""
    global ngrok_process, public_url
    
    try:
        print("🚀 Starting ngrok tunnel...")
        
        # Start ngrok process
        ngrok_process = subprocess.Popen([
            'ngrok', 'http', '5000', '--log=stdout'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # Wait a moment for ngrok to start
        time.sleep(3)
        
        # Get the public URL from ngrok API
        try:
            response = requests.get('http://localhost:4040/api/tunnels')
            if response.status_code == 200:
                tunnels = response.json()['tunnels']
                if tunnels:
                    public_url = tunnels[0]['public_url']
                    print(f"🌐 Ngrok tunnel active: {public_url}")
                    
                    # Update GitHub with the new URL
                    if update_github_url(public_url):
                        print("📝 GitHub repository updated with new URL")
                    else:
                        print("⚠️  Failed to update GitHub repository")
                    
                    return public_url
                else:
                    print("❌ No ngrok tunnels found")
            else:
                print(f"❌ Failed to get ngrok status: {response.status_code}")
        except requests.exceptions.ConnectionError:
            print("❌ Cannot connect to ngrok API. Make sure ngrok is installed and running.")
        except Exception as e:
            print(f"❌ Error getting ngrok URL: {e}")
            
    except FileNotFoundError:
        print("❌ Ngrok not found. Please install ngrok first:")
        print("   1. Download from: https://ngrok.com/download")
        print("   2. Extract and add to PATH, or place in project directory")
        print("   3. Run: ngrok authtoken YOUR_AUTH_TOKEN")
    except Exception as e:
        print(f"❌ Error starting ngrok: {e}")
    
    return None

def stop_ngrok():
    """Stop ngrok tunnel"""
    global ngrok_process
    if ngrok_process:
        try:
            ngrok_process.terminate()
            ngrok_process.wait(timeout=5)
            print("🛑 Ngrok tunnel stopped")
        except:
            ngrok_process.kill()
            print("🛑 Ngrok tunnel force killed")

def monitor_ngrok():
    """Monitor ngrok tunnel and restart if needed"""
    global public_url
    
    while True:
        time.sleep(30)  # Check every 30 seconds
        
        try:
            response = requests.get('http://localhost:4040/api/tunnels', timeout=5)
            if response.status_code == 200:
                tunnels = response.json()['tunnels']
                if tunnels:
                    current_url = tunnels[0]['public_url']
                    if current_url != public_url:
                        public_url = current_url
                        print(f"🔄 Ngrok URL changed: {public_url}")
                        update_github_url(public_url)
                else:
                    print("⚠️  Ngrok tunnel lost, attempting restart...")
                    start_ngrok()
            else:
                print("⚠️  Ngrok API not responding, attempting restart...")
                start_ngrok()
                
        except Exception as e:
            print(f"⚠️  Ngrok monitoring error: {e}")
            # Try to restart ngrok
            start_ngrok()

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
    
    if username == 'admin' and password == 'Admin#804725':
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

@app.route('/api/system-info')
def system_info():
    """Get system information including ngrok URL"""
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    global public_url
    
    info = {
        'local_url': 'http://localhost:5000',
        'public_url': public_url,
        'refresh_interval': REFRESH_INTERVAL,
        'chat_storage_dir': CHAT_STORAGE_DIR,
        'monitored_computers': len(COMPUTERS)
    }
    
    return jsonify(info)

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
    print("=" * 60)
    print("🚀 Network Chat System Starting...")
    print("=" * 60)
    print(f"📊 Refresh interval: {REFRESH_INTERVAL} seconds")
    print(f"💾 Chat storage directory: {CHAT_STORAGE_DIR}")
    print(f"🖥️  Monitoring computers: {', '.join(COMPUTERS)}")
    
    # Start ngrok tunnel
    print("\n🌐 Setting up ngrok tunnel...")
    ngrok_url = start_ngrok()
    
    if ngrok_url:
        print(f"✅ Public URL: {ngrok_url}")
        print(f"🔗 Local URL: http://localhost:5000")
        
        # Start ngrok monitoring in separate thread
        ngrok_monitor_thread = threading.Thread(target=monitor_ngrok, daemon=True)
        ngrok_monitor_thread.start()
    else:
        print("⚠️  Running without ngrok tunnel (local access only)")
        print(f"🔗 Local URL: http://localhost:5000")
    
    # Start file monitoring in a separate thread
    print("\n📁 Starting file monitoring...")
    monitoring_thread = threading.Thread(target=start_file_monitoring, daemon=True)
    monitoring_thread.start()
    
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    print("\n📦 Required packages: flask, watchdog, requests")
    print("💡 Make sure ngrok is installed and authenticated")
    print("\n" + "=" * 60)
    print("🎉 System ready! Access the application at:")
    print(f"   Local:  http://localhost:5000")
    if ngrok_url:
        print(f"   Public: {ngrok_url}")
    print("=" * 60)
    
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        stop_ngrok()
    except Exception as e:
        print(f"❌ Error running Flask app: {e}")
        stop_ngrok()