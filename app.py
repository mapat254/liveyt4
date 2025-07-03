import streamlit as st
import pandas as pd
import subprocess
import threading
import time
import os
import psutil
import datetime
import pytz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
import requests
import json
import shutil
import tempfile
import webbrowser
from urllib.parse import urlparse, parse_qs

# YouTube API scopes
SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']

def get_jakarta_time():
    """Get current time in Jakarta timezone"""
    jakarta_tz = pytz.timezone('Asia/Jakarta')
    return datetime.datetime.now(jakarta_tz)

def format_jakarta_time(dt):
    """Format Jakarta time for display"""
    return dt.strftime('%H:%M WIB')

def get_channel_credentials_path(channel_name):
    """Get credentials file path for specific channel"""
    return f'credentials_{channel_name}.json'

def get_channel_token_path(channel_name):
    """Get token file path for specific channel"""
    return f'token_{channel_name}.json'

def validate_credentials_file(file_content):
    """Validate uploaded credentials file"""
    try:
        data = json.loads(file_content)
        
        # Check for web or installed app credentials
        if 'web' in data:
            creds = data['web']
        elif 'installed' in data:
            creds = data['installed']
        else:
            return False, "Invalid credentials format. Must contain 'web' or 'installed' section."
        
        # Check required fields
        required_fields = ['client_id', 'client_secret', 'auth_uri', 'token_uri']
        missing_fields = [field for field in required_fields if field not in creds]
        
        if missing_fields:
            return False, f"Missing required fields: {', '.join(missing_fields)}"
        
        return True, "Valid credentials file"
        
    except json.JSONDecodeError:
        return False, "Invalid JSON format"
    except Exception as e:
        return False, f"Error validating file: {str(e)}"

def create_oauth_flow(channel_name):
    """Create OAuth flow for authentication"""
    try:
        credentials_path = get_channel_credentials_path(channel_name)
        
        if not os.path.exists(credentials_path):
            return None, "Credentials file not found"
        
        # Create flow with redirect URI for web apps
        flow = Flow.from_client_secrets_file(
            credentials_path,
            scopes=SCOPES,
            redirect_uri='http://localhost:8080'  # Standard redirect for installed apps
        )
        
        return flow, None
        
    except Exception as e:
        return None, f"Error creating OAuth flow: {str(e)}"

def get_youtube_service(channel_name='default'):
    """Get authenticated YouTube service for specific channel"""
    try:
        token_path = get_channel_token_path(channel_name)
        
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            
            # Check if credentials are valid
            if creds and creds.valid:
                return build('youtube', 'v3', credentials=creds)
            
            # Try to refresh if expired
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    # Save refreshed token
                    with open(token_path, 'w') as token:
                        token.write(creds.to_json())
                    return build('youtube', 'v3', credentials=creds)
                except Exception as e:
                    st.error(f"Failed to refresh token for {channel_name}: {e}")
                    return None
        
        return None
        
    except Exception as e:
        st.error(f"Error getting YouTube service for {channel_name}: {e}")
        return None

def is_channel_authenticated(channel_name):
    """Check if channel is authenticated"""
    token_path = get_channel_token_path(channel_name)
    
    if not os.path.exists(token_path):
        return False
    
    try:
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        return creds and creds.valid
    except:
        return False

def get_channel_info(channel_name='default'):
    """Get channel information"""
    try:
        youtube = get_youtube_service(channel_name)
        if not youtube:
            return None
        
        response = youtube.channels().list(
            part='snippet,statistics',
            mine=True
        ).execute()
        
        if response['items']:
            channel = response['items'][0]
            return {
                'title': channel['snippet']['title'],
                'id': channel['id'],
                'subscribers': channel['statistics'].get('subscriberCount', 'N/A'),
                'videos': channel['statistics'].get('videoCount', 'N/A')
            }
        return None
    except Exception as e:
        st.error(f"Error getting channel info for {channel_name}: {e}")
        return None

def create_youtube_broadcast(title, description, start_time_str, privacy_status='public', is_shorts=False, channel_name='default'):
    """Create YouTube live broadcast"""
    try:
        youtube = get_youtube_service(channel_name)
        if not youtube:
            return None, None, f"YouTube service not available for channel '{channel_name}'"
        
        jakarta_tz = pytz.timezone('Asia/Jakarta')
        
        # Handle different time formats
        if start_time_str == "NOW":
            start_time = get_jakarta_time()
            scheduled_start_time = start_time.isoformat()
        else:
            try:
                time_parts = start_time_str.split(':')
                hour = int(time_parts[0])
                minute = int(time_parts[1])
                
                now = get_jakarta_time()
                start_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                if start_time <= now:
                    start_time += datetime.timedelta(days=1)
                
                scheduled_start_time = start_time.isoformat()
            except:
                start_time = get_jakarta_time()
                scheduled_start_time = start_time.isoformat()
        
        # Create broadcast
        broadcast_response = youtube.liveBroadcasts().insert(
            part='snippet,status,contentDetails',
            body={
                'snippet': {
                    'title': title,
                    'description': description,
                    'scheduledStartTime': scheduled_start_time,
                },
                'status': {
                    'privacyStatus': privacy_status,
                    'lifeCycleStatus': 'ready' if start_time_str == "NOW" else 'created'
                },
                'contentDetails': {
                    'enableAutoStart': True,
                    'enableAutoStop': True,
                    'recordFromStart': True,
                    'enableDvr': True,
                    'enableContentEncryption': False,
                    'enableEmbed': True,
                    'latencyPreference': 'low'
                }
            }
        ).execute()
        
        broadcast_id = broadcast_response['id']
        
        # Create live stream
        stream_response = youtube.liveStreams().insert(
            part='snippet,cdn',
            body={
                'snippet': {
                    'title': f"{title} - Stream",
                    'description': f"Live stream for {title}"
                },
                'cdn': {
                    'format': '1080p',
                    'ingestionType': 'rtmp',
                    'resolution': '720p',
                    'frameRate': '30fps'
                }
            }
        ).execute()
        
        stream_id = stream_response['id']
        stream_key = stream_response['cdn']['ingestionInfo']['streamName']
        
        # Bind broadcast to stream
        youtube.liveBroadcasts().bind(
            part='id,contentDetails',
            id=broadcast_id,
            streamId=stream_id
        ).execute()
        
        return broadcast_id, stream_key, None
        
    except HttpError as e:
        error_details = e.error_details[0] if e.error_details else {}
        return None, None, f"YouTube API Error: {error_details.get('message', str(e))}"
    except Exception as e:
        return None, None, f"Error creating broadcast: {str(e)}"

def get_available_channels():
    """Get list of available channels based on credentials files"""
    channels = []
    for file in os.listdir('.'):
        if file.startswith('credentials_') and file.endswith('.json'):
            channel_name = file.replace('credentials_', '').replace('.json', '')
            channels.append(channel_name)
    
    if os.path.exists('credentials.json'):
        channels.append('default')
    
    return sorted(channels)

def get_video_files():
    """Get list of video files from current directory"""
    video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm']
    video_files = []
    
    try:
        for file in os.listdir('.'):
            if any(file.lower().endswith(ext) for ext in video_extensions):
                video_files.append(file)
    except Exception as e:
        st.error(f"Error reading video files: {e}")
    
    return sorted(video_files)

def run_ffmpeg(video_path, streaming_key, is_shorts=False, stream_index=None, quality='720p', broadcast_id=None, channel_name='default'):
    """Run FFmpeg with proper YouTube streaming settings"""
    try:
        quality_settings = {
            '240p': {'resolution': '426x240', 'bitrate': '400k', 'fps': '24'},
            '360p': {'resolution': '640x360', 'bitrate': '800k', 'fps': '24'},
            '480p': {'resolution': '854x480', 'bitrate': '1200k', 'fps': '30'},
            '720p': {'resolution': '1280x720', 'bitrate': '2500k', 'fps': '30'},
            '1080p': {'resolution': '1920x1080', 'bitrate': '4500k', 'fps': '30'}
        }
        
        settings = quality_settings.get(quality, quality_settings['720p'])
        
        cmd = [
            'ffmpeg',
            '-re',
            '-i', video_path,
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-tune', 'zerolatency',
            '-b:v', settings['bitrate'],
            '-maxrate', settings['bitrate'],
            '-bufsize', str(int(settings['bitrate'].replace('k', '')) * 2) + 'k',
            '-s', settings['resolution'],
            '-r', settings['fps'],
            '-g', '60',
            '-keyint_min', '60',
            '-sc_threshold', '0',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-ac', '2',
            '-f', 'flv',
            f'rtmp://a.rtmp.youtube.com/live2/{streaming_key}'
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        if stream_index is not None:
            st.session_state.processes[stream_index] = process
            st.session_state.streams.loc[stream_index, 'PID'] = process.pid
            st.session_state.streams.loc[stream_index, 'Status'] = 'Sedang Live'
            save_persistent_streams(st.session_state.streams)
        
        def monitor_process():
            try:
                stdout, stderr = process.communicate()
                if stream_index is not None and stream_index in st.session_state.processes:
                    del st.session_state.processes[stream_index]
                    st.session_state.streams.loc[stream_index, 'Status'] = 'Selesai'
                    st.session_state.streams.loc[stream_index, 'PID'] = 0
                    save_persistent_streams(st.session_state.streams)
            except Exception as e:
                print(f"Error monitoring process: {e}")
        
        threading.Thread(target=monitor_process, daemon=True).start()
        return True
        
    except Exception as e:
        st.error(f"Error starting stream: {e}")
        return False

def start_stream(video_path, streaming_key, is_shorts=False, stream_index=None, quality='720p', broadcast_id=None, channel_name='default'):
    """Start streaming with proper error handling"""
    if not os.path.exists(video_path):
        st.error(f"❌ Video file not found: {video_path}")
        return False
    
    return run_ffmpeg(video_path, streaming_key, is_shorts, stream_index, quality, broadcast_id, channel_name)

def stop_stream(stream_index):
    """Stop streaming process"""
    try:
        if stream_index in st.session_state.processes:
            process = st.session_state.processes[stream_index]
            process.terminate()
            time.sleep(2)
            
            if process.poll() is None:
                process.kill()
            
            del st.session_state.processes[stream_index]
            st.session_state.streams.loc[stream_index, 'Status'] = 'Dihentikan'
            st.session_state.streams.loc[stream_index, 'PID'] = 0
            save_persistent_streams(st.session_state.streams)
            
            return True
    except Exception as e:
        st.error(f"Error stopping stream: {e}")
        return False

def save_persistent_streams(df):
    """Save streams to persistent storage"""
    try:
        df.to_csv('persistent_streams.csv', index=False)
    except Exception as e:
        st.error(f"Error saving streams: {e}")

def load_persistent_streams():
    """Load streams from persistent storage"""
    try:
        if os.path.exists('persistent_streams.csv'):
            df = pd.read_csv('persistent_streams.csv')
            required_columns = ['Video', 'Streaming Key', 'Jam Mulai', 'Status', 'PID', 'Is Shorts', 'Quality', 'Broadcast ID', 'Channel']
            for col in required_columns:
                if col not in df.columns:
                    if col == 'Channel':
                        df[col] = 'default'
                    elif col in ['Video', 'Streaming Key', 'Jam Mulai', 'Status', 'Broadcast ID']:
                        df[col] = ''
                    elif col == 'Is Shorts':
                        df[col] = False
                    elif col == 'Quality':
                        df[col] = '720p'
                    else:
                        df[col] = 0
            return df
        else:
            return pd.DataFrame(columns=['Video', 'Streaming Key', 'Jam Mulai', 'Status', 'PID', 'Is Shorts', 'Quality', 'Broadcast ID', 'Channel'])
    except Exception as e:
        st.error(f"Error loading streams: {e}")
        return pd.DataFrame(columns=['Video', 'Streaming Key', 'Jam Mulai', 'Status', 'PID', 'Is Shorts', 'Quality', 'Broadcast ID', 'Channel'])

def check_scheduled_streams():
    """Check and start scheduled streams"""
    jakarta_time = get_jakarta_time()
    current_time = format_jakarta_time(jakarta_time)
    
    for idx, row in st.session_state.streams.iterrows():
        if row['Status'] == 'Menunggu':
            start_time = row['Jam Mulai']
            
            if start_time == "NOW":
                quality = row.get('Quality', '720p')
                broadcast_id = row.get('Broadcast ID', None)
                channel_name = row.get('Channel', 'default')
                if start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), idx, quality, broadcast_id, channel_name):
                    st.session_state.streams.loc[idx, 'Jam Mulai'] = current_time
                    save_persistent_streams(st.session_state.streams)
                continue
            
            try:
                scheduled_parts = start_time.replace(' WIB', '').split(':')
                scheduled_hour = int(scheduled_parts[0])
                scheduled_minute = int(scheduled_parts[1])
                
                current_hour = jakarta_time.hour
                current_minute = jakarta_time.minute
                
                if (current_hour > scheduled_hour or 
                    (current_hour == scheduled_hour and current_minute >= scheduled_minute)):
                    
                    quality = row.get('Quality', '720p')
                    broadcast_id = row.get('Broadcast ID', None)
                    channel_name = row.get('Channel', 'default')
                    if start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), idx, quality, broadcast_id, channel_name):
                        st.session_state.streams.loc[idx, 'Jam Mulai'] = current_time
                        save_persistent_streams(st.session_state.streams)
                        
            except Exception as e:
                st.error(f"Error processing scheduled stream: {e}")

# Initialize session state
if 'streams' not in st.session_state:
    st.session_state.streams = load_persistent_streams()

if 'processes' not in st.session_state:
    st.session_state.processes = {}

if 'auth_step' not in st.session_state:
    st.session_state.auth_step = {}

# Streamlit UI
st.set_page_config(page_title="🎬 Multi-Channel YouTube Live Stream Manager", layout="wide")

st.title("🎬 Multi-Channel YouTube Live Stream Manager")
st.markdown("---")

# Auto-refresh for scheduled streams
check_scheduled_streams()

# Main tabs
tab1, tab2, tab3 = st.tabs(["📺 Stream Manager", "🔧 Channel Management", "📊 Dashboard"])

with tab2:
    st.header("🔧 Channel Management")
    
    # Add new channel section
    st.subheader("➕ Add New Channel")
    
    with st.form("add_channel_form", clear_on_submit=True):
        col1, col2 = st.columns([1, 1])
        
        with col1:
            channel_name = st.text_input(
                "📝 Channel Name", 
                placeholder="e.g., main-channel, gaming-channel",
                help="Enter a unique name for this channel"
            )
        
        with col2:
            uploaded_file = st.file_uploader(
                "📤 Upload credentials.json", 
                type=['json'],
                help="Upload the OAuth2 credentials file from Google Cloud Console"
            )
        
        submit_button = st.form_submit_button("💾 Save Channel")
        
        if submit_button:
            if not channel_name:
                st.error("❌ Please enter a channel name")
            elif not uploaded_file:
                st.error("❌ Please upload a credentials file")
            else:
                # Read and validate file
                file_content = uploaded_file.read().decode('utf-8')
                is_valid, message = validate_credentials_file(file_content)
                
                if not is_valid:
                    st.error(f"❌ {message}")
                else:
                    try:
                        # Save credentials file
                        credentials_path = get_channel_credentials_path(channel_name)
                        with open(credentials_path, 'w') as f:
                            f.write(file_content)
                        
                        st.success(f"✅ Channel '{channel_name}' credentials saved successfully!")
                        st.info("📝 Now you need to authenticate this channel. See the channel list below.")
                        time.sleep(1)
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Error saving credentials: {e}")
    
    st.markdown("---")
    
    # Existing channels section
    st.subheader("📋 Existing Channels")
    
    available_channels = get_available_channels()
    
    if available_channels:
        for channel in available_channels:
            with st.container():
                col1, col2, col3 = st.columns([2, 2, 1])
                
                with col1:
                    st.write(f"**📺 {channel}**")
                    
                    # Check authentication status
                    is_authenticated = is_channel_authenticated(channel)
                    
                    if is_authenticated:
                        st.success("✅ Authenticated")
                        
                        # Get channel info
                        channel_info = get_channel_info(channel)
                        if channel_info:
                            st.caption(f"📊 {channel_info['title']}")
                            st.caption(f"👥 {channel_info['subscribers']} subscribers | 🎥 {channel_info['videos']} videos")
                    else:
                        st.error("❌ Not Authenticated")
                        st.caption("Click 'Authenticate' to connect this channel")
                
                with col2:
                    if not is_authenticated:
                        # Authentication process
                        auth_key = f"auth_{channel}"
                        
                        if auth_key not in st.session_state.auth_step:
                            st.session_state.auth_step[auth_key] = "start"
                        
                        if st.session_state.auth_step[auth_key] == "start":
                            if st.button(f"🔐 Authenticate {channel}", key=f"auth_btn_{channel}"):
                                # Create OAuth flow
                                flow, error = create_oauth_flow(channel)
                                
                                if error:
                                    st.error(f"❌ {error}")
                                else:
                                    # Generate authorization URL
                                    auth_url, _ = flow.authorization_url(prompt='consent')
                                    
                                    # Store flow in session state
                                    st.session_state[f"flow_{channel}"] = flow
                                    st.session_state[f"auth_url_{channel}"] = auth_url
                                    st.session_state.auth_step[auth_key] = "waiting_code"
                                    st.rerun()
                        
                        elif st.session_state.auth_step[auth_key] == "waiting_code":
                            st.info("🔗 **Step 1:** Click the link below to authorize:")
                            
                            auth_url = st.session_state.get(f"auth_url_{channel}", "")
                            if auth_url:
                                st.markdown(f"[🔗 **Authorize {channel}**]({auth_url})")
                                
                                st.info("📋 **Step 2:** Copy the authorization code and paste it below:")
                                
                                with st.form(f"auth_code_form_{channel}"):
                                    auth_code = st.text_input(
                                        "Authorization Code",
                                        placeholder="Paste the code from Google here...",
                                        key=f"auth_code_{channel}"
                                    )
                                    
                                    col_submit, col_cancel = st.columns(2)
                                    
                                    with col_submit:
                                        if st.form_submit_button("✅ Complete Authentication"):
                                            if auth_code:
                                                try:
                                                    # Complete OAuth flow
                                                    flow = st.session_state.get(f"flow_{channel}")
                                                    if flow:
                                                        # Exchange code for token
                                                        flow.fetch_token(code=auth_code)
                                                        
                                                        # Save credentials
                                                        token_path = get_channel_token_path(channel)
                                                        with open(token_path, 'w') as token:
                                                            token.write(flow.credentials.to_json())
                                                        
                                                        # Clean up session state
                                                        st.session_state.auth_step[auth_key] = "start"
                                                        if f"flow_{channel}" in st.session_state:
                                                            del st.session_state[f"flow_{channel}"]
                                                        if f"auth_url_{channel}" in st.session_state:
                                                            del st.session_state[f"auth_url_{channel}"]
                                                        
                                                        st.success(f"✅ {channel} authenticated successfully!")
                                                        time.sleep(1)
                                                        st.rerun()
                                                        
                                                except Exception as e:
                                                    st.error(f"❌ Authentication failed: {e}")
                                            else:
                                                st.error("❌ Please enter the authorization code")
                                    
                                    with col_cancel:
                                        if st.form_submit_button("❌ Cancel"):
                                            st.session_state.auth_step[auth_key] = "start"
                                            st.rerun()
                    else:
                        # Re-authenticate option for authenticated channels
                        if st.button(f"🔄 Re-authenticate", key=f"reauth_{channel}"):
                            # Remove existing token
                            token_path = get_channel_token_path(channel)
                            if os.path.exists(token_path):
                                os.remove(token_path)
                            
                            # Reset auth step
                            auth_key = f"auth_{channel}"
                            st.session_state.auth_step[auth_key] = "start"
                            st.rerun()
                
                with col3:
                    if st.button(f"🗑️ Remove", key=f"remove_{channel}"):
                        try:
                            # Remove credentials and token files
                            credentials_path = get_channel_credentials_path(channel)
                            token_path = get_channel_token_path(channel)
                            
                            if os.path.exists(credentials_path):
                                os.remove(credentials_path)
                            if os.path.exists(token_path):
                                os.remove(token_path)
                            
                            # Clean up session state
                            auth_key = f"auth_{channel}"
                            if auth_key in st.session_state.auth_step:
                                del st.session_state.auth_step[auth_key]
                            
                            st.success(f"✅ Channel '{channel}' removed")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error removing channel: {e}")
                
                st.markdown("---")
    else:
        st.info("📝 No channels configured. Add a channel above to get started!")

with tab1:
    st.header("📋 Stream Manager")
    
    # Sidebar for YouTube Broadcast Creation
    with st.sidebar:
        st.header("📺 Create YouTube Broadcast")
        
        available_channels = get_available_channels()
        authenticated_channels = [ch for ch in available_channels if is_channel_authenticated(ch)]
        
        if not authenticated_channels:
            st.warning("⚠️ No authenticated channels available. Please authenticate channels first.")
        else:
            selected_channel = st.selectbox("📺 Select Channel", authenticated_channels)
            
            if selected_channel:
                channel_info = get_channel_info(selected_channel)
                if channel_info:
                    st.info(f"📊 **{channel_info['title']}**\n👥 {channel_info['subscribers']} subscribers")
            
            with st.form("broadcast_form"):
                title = st.text_input("🎬 Broadcast Title", value="Live Stream")
                description = st.text_area("📝 Description", value="Live streaming content")
                privacy = st.selectbox("🔒 Privacy", ['public', 'unlisted', 'private'], index=0)
                
                jakarta_time = get_jakarta_time()
                current_time_str = format_jakarta_time(jakarta_time)
                st.write(f"🕐 Current Time: **{current_time_str}**")
                
                col1, col2, col3, col4 = st.columns(4)
                
                start_immediately = False
                broadcast_time = None
                
                with col1:
                    if st.form_submit_button("🚀 NOW"):
                        broadcast_time = jakarta_time.time()
                        start_immediately = True
                
                with col2:
                    if st.form_submit_button("⏰ +5min"):
                        future_time = jakarta_time + datetime.timedelta(minutes=5)
                        broadcast_time = future_time.time()
                
                with col3:
                    if st.form_submit_button("⏰ +15min"):
                        future_time = jakarta_time + datetime.timedelta(minutes=15)
                        broadcast_time = future_time.time()
                
                with col4:
                    if st.form_submit_button("⏰ +30min"):
                        future_time = jakarta_time + datetime.timedelta(minutes=30)
                        broadcast_time = future_time.time()
                
                if not broadcast_time:
                    manual_time = st.time_input("🕐 Or set custom time", value=jakarta_time.time())
                    if st.form_submit_button("📅 Schedule"):
                        broadcast_time = manual_time
                
                if broadcast_time and selected_channel:
                    with st.spinner(f"Creating YouTube broadcast on '{selected_channel}'..."):
                        time_str = "NOW" if start_immediately else broadcast_time.strftime('%H:%M')
                        
                        broadcast_id, stream_key, error = create_youtube_broadcast(
                            title, description, time_str, privacy, False, selected_channel
                        )
                        
                        if error:
                            st.error(f"❌ {error}")
                        else:
                            st.success(f"✅ Broadcast created successfully on '{selected_channel}'!")
                            st.info(f"🔑 Stream Key: `{stream_key}`")
                            st.info(f"🆔 Broadcast ID: `{broadcast_id}`")
                            
                            video_files = get_video_files()
                            if video_files:
                                selected_video = st.selectbox("📹 Select video to stream", video_files)
                                quality = st.selectbox("🎥 Quality", ['240p', '360p', '480p', '720p', '1080p'], index=3)
                                is_shorts = st.checkbox("📱 YouTube Shorts format")
                                
                                if st.button("➕ Add to Stream Manager"):
                                    new_stream = pd.DataFrame({
                                        'Video': [selected_video],
                                        'Streaming Key': [stream_key],
                                        'Jam Mulai': [time_str],
                                        'Status': ['Menunggu'],
                                        'PID': [0],
                                        'Is Shorts': [is_shorts],
                                        'Quality': [quality],
                                        'Broadcast ID': [broadcast_id],
                                        'Channel': [selected_channel]
                                    })
                                    
                                    st.session_state.streams = pd.concat([st.session_state.streams, new_stream], ignore_index=True)
                                    save_persistent_streams(st.session_state.streams)
                                    st.success("✅ Stream added to manager!")
                                    st.rerun()

    # Main content area
    col1, col2 = st.columns([2, 1])

    with col1:
        # Add new stream form
        with st.expander("➕ Add New Stream", expanded=False):
            with st.form("add_stream"):
                video_files = get_video_files()
                authenticated_channels = [ch for ch in get_available_channels() if is_channel_authenticated(ch)]
                
                if not video_files:
                    st.warning("⚠️ No video files found in current directory")
                    st.stop()
                
                if not authenticated_channels:
                    st.warning("⚠️ No authenticated channels available.")
                    st.stop()
                
                selected_video = st.selectbox("📹 Select Video", video_files)
                selected_channel = st.selectbox("📺 Select Channel", authenticated_channels)
                streaming_key = st.text_input("🔑 Streaming Key", help="Your YouTube streaming key")
                
                jakarta_time = get_jakarta_time()
                current_time_str = format_jakarta_time(jakarta_time)
                st.write(f"🕐 Current Time: **{current_time_str}**")
                
                col_now, col_5, col_15, col_30 = st.columns(4)
                
                schedule_time = None
                
                with col_now:
                    if st.form_submit_button("🚀 NOW"):
                        schedule_time = "NOW"
                
                with col_5:
                    if st.form_submit_button("⏰ +5min"):
                        future_time = jakarta_time + datetime.timedelta(minutes=5)
                        schedule_time = format_jakarta_time(future_time)
                
                with col_15:
                    if st.form_submit_button("⏰ +15min"):
                        future_time = jakarta_time + datetime.timedelta(minutes=15)
                        schedule_time = format_jakarta_time(future_time)
                
                with col_30:
                    if st.form_submit_button("⏰ +30min"):
                        future_time = jakarta_time + datetime.timedelta(minutes=30)
                        schedule_time = format_jakarta_time(future_time)
                
                if not schedule_time:
                    manual_time = st.time_input("🕐 Or set custom time", value=jakarta_time.time())
                    quality = st.selectbox("🎥 Quality", ['240p', '360p', '480p', '720p', '1080p'], index=3)
                    is_shorts = st.checkbox("📱 YouTube Shorts format")
                    
                    if st.form_submit_button("📅 Add Stream"):
                        schedule_time = format_jakarta_time(
                            jakarta_time.replace(hour=manual_time.hour, minute=manual_time.minute, second=0, microsecond=0)
                        )
                
                if schedule_time and streaming_key and selected_channel:
                    new_stream = pd.DataFrame({
                        'Video': [selected_video],
                        'Streaming Key': [streaming_key],
                        'Jam Mulai': [schedule_time],
                        'Status': ['Menunggu'],
                        'PID': [0],
                        'Is Shorts': [is_shorts if 'is_shorts' in locals() else False],
                        'Quality': [quality if 'quality' in locals() else '720p'],
                        'Broadcast ID': [''],
                        'Channel': [selected_channel]
                    })
                    
                    st.session_state.streams = pd.concat([st.session_state.streams, new_stream], ignore_index=True)
                    save_persistent_streams(st.session_state.streams)
                    st.success("✅ Stream added successfully!")
                    st.rerun()

        # Display streams
        if not st.session_state.streams.empty:
            st.subheader("📺 Active Streams")
            
            for idx, row in st.session_state.streams.iterrows():
                with st.container():
                    card_col1, card_col2, card_col3, card_col4 = st.columns([3, 2, 2, 2])
                    
                    with card_col1:
                        st.write(f"**📹 {row['Video']}**")
                        st.caption(f"📺 Channel: {row.get('Channel', 'default')} | Quality: {row.get('Quality', '720p')}")
                        
                        if row.get('Broadcast ID') and row['Broadcast ID'] != '':
                            youtube_url = f"https://youtube.com/watch?v={row['Broadcast ID']}"
                            st.markdown(f"🔗 [Watch on YouTube]({youtube_url})")
                        
                        st.caption(f"Key: {row['Streaming Key'][:8]}****")
                    
                    with card_col2:
                        st.write(f"🕐 **{row['Jam Mulai']}**")
                    
                    with card_col3:
                        status = row['Status']
                        if status == 'Sedang Live':
                            st.success(f"🟢 {status}")
                        elif status == 'Menunggu':
                            st.warning(f"🟡 {status}")
                        elif status == 'Selesai':
                            st.info(f"🔵 {status}")
                        else:
                            st.error(f"🔴 {status}")
                    
                    with card_col4:
                        if row['Status'] == 'Menunggu':
                            if st.button(f"▶️ Start Now", key=f"start_{idx}"):
                                quality = row.get('Quality', '720p')
                                broadcast_id = row.get('Broadcast ID', None)
                                channel_name = row.get('Channel', 'default')
                                if start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), idx, quality, broadcast_id, channel_name):
                                    st.session_state.streams.loc[idx, 'Status'] = 'Sedang Live'
                                    st.session_state.streams.loc[idx, 'Jam Mulai'] = format_jakarta_time(get_jakarta_time())
                                    save_persistent_streams(st.session_state.streams)
                                    st.rerun()
                        
                        elif row['Status'] == 'Sedang Live':
                            if st.button(f"⏹️ Stop Stream", key=f"stop_{idx}"):
                                if stop_stream(idx):
                                    st.rerun()
                        
                        if st.button(f"🗑️ Delete", key=f"delete_{idx}"):
                            if row['Status'] == 'Sedang Live':
                                stop_stream(idx)
                            st.session_state.streams = st.session_state.streams.drop(idx).reset_index(drop=True)
                            save_persistent_streams(st.session_state.streams)
                            st.rerun()
                    
                    st.markdown("---")
        else:
            st.info("📝 No streams configured. Add a stream to get started!")

    with col2:
        st.header("📊 System Status")
        
        jakarta_time = get_jakarta_time()
        st.metric("🕐 Current Time", format_jakarta_time(jakarta_time))
        
        active_streams = len(st.session_state.streams[st.session_state.streams['Status'] == 'Sedang Live'])
        st.metric("📺 Active Streams", active_streams)
        
        waiting_streams = len(st.session_state.streams[st.session_state.streams['Status'] == 'Menunggu'])
        st.metric("⏳ Waiting Streams", waiting_streams)
        
        authenticated_channels = [ch for ch in get_available_channels() if is_channel_authenticated(ch)]
        st.metric("📺 Authenticated Channels", len(authenticated_channels))
        
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            st.metric("💻 CPU Usage", f"{cpu_percent:.1f}%")
            st.metric("🧠 Memory Usage", f"{memory.percent:.1f}%")
        except:
            st.info("System monitoring unavailable")
        
        if st.button("🔄 Refresh Status"):
            st.rerun()

with tab3:
    st.header("📊 Multi-Channel Dashboard")
    
    authenticated_channels = [ch for ch in get_available_channels() if is_channel_authenticated(ch)]
    
    if authenticated_channels:
        st.subheader("📺 Channel Overview")
        
        for channel in authenticated_channels:
            with st.expander(f"📺 {channel}", expanded=True):
                col1, col2, col3 = st.columns(3)
                
                channel_info = get_channel_info(channel)
                
                with col1:
                    if channel_info:
                        st.metric("📊 Channel", channel_info['title'])
                        st.metric("👥 Subscribers", channel_info['subscribers'])
                    else:
                        st.warning("⚠️ Unable to fetch channel info")
                
                with col2:
                    channel_streams = st.session_state.streams[st.session_state.streams['Channel'] == channel]
                    active_count = len(channel_streams[channel_streams['Status'] == 'Sedang Live'])
                    waiting_count = len(channel_streams[channel_streams['Status'] == 'Menunggu'])
                    
                    st.metric("🟢 Active Streams", active_count)
                    st.metric("🟡 Waiting Streams", waiting_count)
                
                with col3:
                    if channel_info:
                        st.metric("🎥 Total Videos", channel_info['videos'])
                    
                    if st.button(f"🔄 Refresh {channel}", key=f"refresh_{channel}"):
                        st.rerun()
        
        if not st.session_state.streams.empty:
            st.subheader("📈 Stream Distribution by Channel")
            channel_counts = st.session_state.streams['Channel'].value_counts()
            st.bar_chart(channel_counts)
            
            st.subheader("📊 Stream Status Distribution")
            status_counts = st.session_state.streams['Status'].value_counts()
            st.bar_chart(status_counts)
    
    else:
        st.info("📝 No authenticated channels available. Please authenticate channels in the Channel Management tab.")

# Footer
st.markdown("---")
st.markdown("🎬 **Multi-Channel YouTube Live Stream Manager** - Manage multiple YouTube channels with automated streaming")
