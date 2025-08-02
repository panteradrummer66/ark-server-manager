from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import configparser
import subprocess
import os
import json
import psutil

app = Flask(__name__)
app.secret_key = 'super-secret-key'  # Change this for security!

login_manager = LoginManager()
login_manager.init_app(app)

USERS = {
    "admin": {"password": "changeme", "role": "admin"},
    "leslie": {"password": "leslie", "role": "user"},
}

class User(UserMixin):
    def __init__(self, id):
        self.id = id
        self.role = USERS.get(id, {}).get("role", "user")

@login_manager.user_loader
def load_user(user_id):
    if user_id in USERS:
        user = User(user_id)
        user.role = USERS[user_id]["role"]
        return user
    return None

def load_servers():
    if not os.path.exists('servers.json'):
        return []
    with open('servers.json', 'r') as f:
        return json.load(f)

def save_servers(servers):
    with open('servers.json', 'w') as f:
        json.dump(servers, f, indent=2)

def get_server_status(server):
    exe_name = "ArkAscendedServer.exe"
    folder = os.path.abspath(server["folder"]).lower()
    for proc in psutil.process_iter(['name', 'cwd']):
        try:
            if proc.info['name'] == exe_name and proc.info['cwd']:
                proc_cwd = os.path.abspath(proc.info['cwd']).lower()
                if proc_cwd.startswith(folder):
                    return "running"
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            continue
    return "stopped"

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in USERS and password == USERS[username]["password"]:
            user = User(username)
            user.role = USERS[username]["role"]
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials.")
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    servers = load_servers()
    statuses = [get_server_status(server) for server in servers]
    return render_template('dashboard.html', servers=servers, statuses=statuses)

@app.route('/api/server_status')
@login_required
def api_server_status():
    servers = load_servers()
    statuses = [get_server_status(server) for server in servers]
    return jsonify({'statuses': statuses})

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/edit_ini/<int:server_idx>/<which>', methods=['GET', 'POST'])
@login_required
def edit_ini(server_idx, which):
    servers = load_servers()
    try:
        server = servers[server_idx]
    except IndexError:
        flash("Server not found.")
        return redirect(url_for('dashboard'))
    ini_path = server['game_ini'] if which == "game" else server['gameusersettings_ini']
    config = configparser.ConfigParser(strict=False)
    config.optionxform = str
    config.read(ini_path)
    if request.method == 'POST':
        for section in config.sections():
            for key in config[section]:
                field_name = f"{section}__{key}"
                if field_name in request.form:
                    config[section][key] = request.form[field_name]
        with open(ini_path + '.bak', 'w') as backup:
            config.write(backup)
        with open(ini_path, 'w') as configfile:
            config.write(configfile)
        flash("Settings saved!")
        return redirect(url_for('edit_ini', server_idx=server_idx, which=which))
    return render_template('edit_ini.html', config=config, inifile=os.path.basename(ini_path), server=server, server_idx=server_idx, which=which)

@app.route('/server/<int:server_idx>/<action>')
@login_required
def server_control(server_idx, action):
    servers = load_servers()
    try:
        server = servers[server_idx]
    except IndexError:
        flash("Server not found.")
        return redirect(url_for('dashboard'))
    folder = server['folder']
    try:
        if action == 'start':
            subprocess.Popen([server['start_script']], cwd=folder, shell=True)
            flash(f"{server['name']} starting!")
        elif action == 'stop':
            subprocess.Popen([server['stop_script']], cwd=folder, shell=True)
            flash(f"{server['name']} stopping!")
        elif action == 'restart':
            subprocess.Popen([server['stop_script']], cwd=folder, shell=True)
            subprocess.Popen([server['start_script']], cwd=folder, shell=True)
            flash(f"{server['name']} restarting!")
    except Exception as e:
        flash(f"Error running action '{action}' for {server['name']}: {e}")
    return redirect(url_for('dashboard'))

@app.route('/api/server_update/<int:server_idx>', methods=['POST'])
@login_required
def api_server_update(server_idx):
    servers = load_servers()
    try:
        server = servers[server_idx]
    except IndexError:
        return jsonify({'success': False, 'msg': "Server not found."}), 404
    folder = server['folder']
    try:
        result = subprocess.run(['update.bat'], cwd=folder, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            return jsonify({'success': True, 'msg': f"{server['name']} update complete!<br><pre>{result.stdout}</pre>"})
        else:
            return jsonify({'success': False, 'msg': f"Update failed for {server['name']}.<br><pre>{result.stderr}</pre>"})
    except Exception as e:
        return jsonify({'success': False, 'msg': f"Error running update: {e}"})

@app.route('/add_server', methods=['GET', 'POST'])
@login_required
def add_server():
    if current_user.role != "admin":
        flash("Only admin users can add servers.")
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        servers = load_servers()
        new_server = {
            "name": request.form['name'],
            "folder": request.form['folder'],
            "start_script": request.form['start_script'],
            "stop_script": request.form['stop_script'],
            "game_ini": request.form['game_ini'],
            "gameusersettings_ini": request.form['gameusersettings_ini']
        }
        servers.append(new_server)
        save_servers(servers)
        flash("Server added!")
        return redirect(url_for('dashboard'))
    return render_template('add_server.html')

@app.route('/delete_server/<int:server_idx>', methods=['POST'])
@login_required
def delete_server(server_idx):
    if current_user.role != "admin":
        flash("Only admin users can delete servers.")
        return redirect(url_for('dashboard'))
    servers = load_servers()
    try:
        removed = servers.pop(server_idx)
        save_servers(servers)
        flash(f"Deleted server: {removed['name']}")
    except IndexError:
        flash("Server not found.")
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    context = ('cert.pem', 'key.pem')  # Or use your external cert+key files
    app.run(host='0.0.0.0', port=5443, ssl_context=context)
