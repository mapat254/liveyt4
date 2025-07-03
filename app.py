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
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
import requests
import json
import shutil

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
    """Validate if uploaded file is a valid Google API credentials file"""
    try:
        data = json.loads(file_content)
        
        # Check if it's a valid Google API credentials file
        if 'installed' in data:
            required_fields = ['client_id', 'client_secret', 'auth_uri', 'token_uri']
            installed = data['installed']
            
            for field in required_fields:
                if field not in installed:
                    return False, f"Missing required field: {field}"
            
            return True, "Valid Google API credentials file"
        else:
            return False, "Invalid credentials file format. Please upload a valid Google API credentials file."
    
    except json.JSONDecodeError:
        return False, "Invalid JSON file format"
    except Exception as e:
        return False, f"Error validating file: {str(e)}"

def authenticate_channel(channel_name):
    """Authenticate a specific channel and get YouTube service"""
    try:
        credentials_path = get_channel_credentials_path(channel_name)
        token_path = get_channel_token_path(channel_name)
        
        if not os.path.exists(credentials_path):
            return None, f"Credentials file not found for channel '{channel_name}'"
        
        # Start OAuth flow
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
        
        # Use run_local_server for authentication
        creds = flow.run_local_server(port=0, open_browser=True)
        
        # Save the credentials for future use
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
        
        # Test the connection
        youtube = build('youtube', 'v3', credentials=creds)
        response = youtube.channels().list(part='snippet,statistics', mine=True).execute()
        
        if response['items']:
            channel_info = response['items'][0]
            return youtube, f"Successfully authenticated channel: {channel_info['snippet']['title']}"
        else:
            return None, "Authentication successful but no channel found"
            
    except Exception as e:
        return None, f"Authentication failed: {str(e)}"

def get_youtube_service(channel_name='default'):
    """Get authenticated YouTube service for specific channel"""
    creds = None
    token_path = get_channel_token_path(channel_name)
    credentials_path = get_channel_credentials_path(channel_name)
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save refreshed token
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
            except Exception as e:
                # Token refresh failed, need re-authentication
                return None
        else:
            # Need initial authentication
            return None
    
    return build('youtube', 'v3', credentials=creds)

def get_channel_info(channel_name='default'):
    """Get channel information"""
    try:
        youtube = get_youtube_service(channel_name)
        if not youtube:
            return None
        
        response = youtube.channels().list(
            part='snippet,statistics,brandingSettings',
            mine=True
        ).execute()
        
        if response['items']:
            channel = response['items'][0]
            return {
                'title': channel['snippet']['title'],
                'id': channel['id'],
                'description': channel['snippet'].get('description', '')[:100] + '...' if len(channel['snippet'].get('description', '')) > 100 else channel['snippet'].get('description', ''),
                'subscribers': channel['statistics'].get('subscriberCount', 'N/A'),
                'videos': channel['statistics'].get('videoCount', 'N/A'),
                'views': channel['statistics'].get('viewCount', 'N/A'),
                'country': channel['snippet'].get('country', 'N/A'),
                'custom_url': channel['snippet'].get('customUrl', 'N/A'),
                'thumbnail': channel['snippet']['thumbnails'].get('default', {}).get('url', ''),
                'created_at': channel['snippet'].get('publishedAt', 'N/A')
            }
        return None
    except Exception as e:
        st.error(f"Error getting channel info for {channel_name}: {e}")
        return None

def is_channel_authenticated(channel_name):
    """Check if channel is authenticated"""
    token_path = get_channel_token_path(channel_name)
    credentials_path = get_channel_credentials_path(channel_name)
    
    if not os.path.exists(credentials_path):
        return False
    
    if not os.path.exists(token_path):
        return False
    
    try:
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        return creds and creds.valid
    except:
        return False

def create_youtube_broadcast(title, description, start_time_str, privacy_status='public', is_shorts=False, channel_name='default'):
    """Create YouTube live broadcast with proper time synchronization"""
    try:
        youtube = get_youtube_service(channel_name)
        if not youtube:
            return None, None, f"YouTube service not available for channel '{channel_name}'. Please authenticate first."
        
        jakarta_tz = pytz.timezone('Asia/Jakarta')
        
        # Handle different time formats
        if start_time_str == "NOW":
            # For NOW broadcasts, set start time to current time
            start_time = get_jakarta_time()
            scheduled_start_time = start_time.isoformat()
        else:
            try:
                # Parse time string (HH:MM format)
                time_parts = start_time_str.split(':')
                hour = int(time_parts[0])
                minute = int(time_parts[1])
                
                # Create datetime for today with specified time
                now = get_jakarta_time()
                start_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # If time has passed today, schedule for tomorrow
                if start_time <= now:
                    start_time += datetime.timedelta(days=1)
                
                scheduled_start_time = start_time.isoformat()
            except:
                # Fallback to current time
                start_time = get_jakarta_time()
                scheduled_start_time = start_time.isoformat()
        
        # Broadcast snippet
        broadcast_snippet = {
            'title': title,
            'description': description,
            'scheduledStartTime': scheduled_start_time,
        }
        
        # Broadcast status - CRITICAL: Use 'ready' for immediate streams
        if start_time_str == "NOW":
            broadcast_status = {
                'privacyStatus': privacy_status,
                'lifeCycleStatus': 'ready'  # Ready to go live immediately
            }
        else:
            broadcast_status = {
                'privacyStatus': privacy_status,
                'lifeCycleStatus': 'created'  # Scheduled for later
            }
        
        # Create broadcast
        broadcast_response = youtube.liveBroadcasts().insert(
            part='snippet,status,contentDetails',
            body={
                'snippet': broadcast_snippet,
                'status': broadcast_status,
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
        
        # Create live stream with proper resolution
        stream_snippet = {
            'title': f"{title} - Stream",
            'description': f"Live stream for {title}"
        }
        
        # Set resolution based on quality
        resolution_map = {
            '240p': '240p',
            '360p': '360p', 
            '480p': '480p',
            '720p': '720p',
            '1080p': '1080p'
        }
        
        stream_cdn = {
            'format': '1080p',  # Default format
            'ingestionType': 'rtmp',
            'resolution': resolution_map.get('720p', '720p'),
            'frameRate': '30fps'
        }
        
        stream_response = youtube.liveStreams().insert(
            part='snippet,cdn',
            body={
                'snippet': stream_snippet,
                'cdn': stream_cdn
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
        
        # For NOW broadcasts, transition to live immediately
        if start_time_str == "NOW":
            try:
                # Wait a moment for binding to complete
                time.sleep(2)
                
                # Transition to testing state first
                youtube.liveBroadcasts().transition(
                    broadcastStatus='testing',
                    id=broadcast_id,
                    part='id,status'
                ).execute()
                
                st.success(f"✅ Broadcast created and ready to go live on channel '{channel_name}'!")
                
            except Exception as e:
                st.warning(f"⚠️ Broadcast created but transition failed: {str(e)}")
        
        return broadcast_id, stream_key, None
        
    except HttpError as e:
        error_details = e.error_details[0] if e.error_details else {}
        return None, None, f"YouTube API Error for channel '{channel_name}': {error_details.get('message', str(e))}"
    except Exception as e:
        return None, None, f"Error creating broadcast for channel '{channel_name}': {str(e)}"

def start_youtube_broadcast(broadcast_id, channel_name='default'):
    """Start YouTube broadcast - transition from testing to live"""
    try:
        youtube = get_youtube_service(channel_name)
        if not youtube:
            return False, f"YouTube service not available for channel '{channel_name}'"
        
        # Get current broadcast status
        broadcast_response = youtube.liveBroadcasts().list(
            part='status,snippet',
            id=broadcast_id
        ).execute()
        
        if not broadcast_response['items']:
            return False, "Broadcast not found"
        
        current_status = broadcast_response['items'][0]['status']['lifeCycleStatus']
        
        # Transition based on current status
        if current_status == 'ready':
            # Transition to testing first
            youtube.liveBroadcasts().transition(
                broadcastStatus='testing',
                id=broadcast_id,
                part='id,status'
            ).execute()
            time.sleep(3)  # Wait for transition
            
            # Then transition to live
            youtube.liveBroadcasts().transition(
                broadcastStatus='live',
                id=broadcast_id,
                part='id,status'
            ).execute()
            
        elif current_status == 'testing':
            # Direct transition to live
            youtube.liveBroadcasts().transition(
                broadcastStatus='live',
                id=broadcast_id,
                part='id,status'
            ).execute()
        
        return True, f"Broadcast started successfully on channel '{channel_name}'"
        
    except HttpError as e:
        error_details = e.error_details[0] if e.error_details else {}
        return False, f"Failed to start broadcast on channel '{channel_name}': {error_details.get('message', str(e))}"
    except Exception as e:
        return False, f"Error starting broadcast on channel '{channel_name}': {str(e)}"

def stop_youtube_broadcast(broadcast_id, channel_name='default'):
    """Stop YouTube broadcast"""
    try:
        youtube = get_youtube_service(channel_name)
        if not youtube:
            return False, f"YouTube service not available for channel '{channel_name}'"
        
        youtube.liveBroadcasts().transition(
            broadcastStatus='complete',
            id=broadcast_id,
            part='id,status'
        ).execute()
        
        return True, f"Broadcast stopped successfully on channel '{channel_name}'"
        
    except Exception as e:
        return False, f"Error stopping broadcast on channel '{channel_name}': {str(e)}"

def upload_thumbnail(video_id, thumbnail_path, channel_name='default'):
    """Upload thumbnail to YouTube video"""
    try:
        youtube = get_youtube_service(channel_name)
        if not youtube:
            return False, f"YouTube service not available for channel '{channel_name}'"
        
        if not os.path.exists(thumbnail_path):
            return False, "Thumbnail file not found"
        
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path)
        ).execute()
        
        return True, f"Thumbnail uploaded successfully to channel '{channel_name}'"
        
    except HttpError as e:
        if e.resp.status == 429:
            return False, "Rate limit exceeded. Please try again later."
        error_details = e.error_details[0] if e.error_details else {}
        return False, f"Failed to upload thumbnail to channel '{channel_name}': {error_details.get('message', str(e))}"
    except Exception as e:
        return False, f"Error uploading thumbnail to channel '{channel_name}': {str(e)}"

def get_available_channels():
    """Get list of available channels based on credentials files"""
    channels = []
    for file in os.listdir('.'):
        if file.startswith('credentials_') and file.endswith('.json'):
            channel_name = file.replace('credentials_', '').replace('.json', '')
            channels.append(channel_name)
    
    # Add default if credentials.json exists
    if os.path.exists('credentials.json'):
        channels.append('default')
    
    return sorted(channels)

def save_channel_config():
    """Save channel configuration"""
    try:
        config = {
            'channels': st.session_state.get('channel_configs', {})
        }
        with open('channel_config.json', 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        st.error(f"Error saving channel config: {e}")

def load_channel_config():
    """Load channel configuration"""
    try:
        if os.path.exists('channel_config.json'):
            with open('channel_config.json', 'r') as f:
                config = json.load(f)
                return config.get('channels', {})
        return {}
    except Exception as e:
        st.error(f"Error loading channel config: {e}")
        return {}

# Initialize session state
if 'streams' not in st.session_state:
    st.session_state.streams = pd.DataFrame(columns=[
        'Video', 'Streaming Key', 'Jam Mulai', 'Status', 'PID', 'Is Shorts', 'Quality', 'Broadcast ID', 'Channel'
    ])

if 'processes' not in st.session_state:
    st.session_state.processes = {}

if 'channel_configs' not in st.session_state:
    st.session_state.channel_configs = load_channel_config()

if 'uploaded_credentials' not in st.session_state:
    st.session_state.uploaded_credentials = {}

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
            # Ensure all required columns exist
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

# Load persistent streams on startup
if st.session_state.streams.empty:
    st.session_state.streams = load_persistent_streams()

def run_ffmpeg(video_path, streaming_key, is_shorts=False, stream_index=None, quality='720p', broadcast_id=None, channel_name='default'):
    """Run FFmpeg with proper YouTube streaming settings"""
    try:
        # Quality settings
        quality_settings = {
            '240p': {'resolution': '426x240', 'bitrate': '400k', 'fps': '24'},
            '360p': {'resolution': '640x360', 'bitrate': '800k', 'fps': '24'},
            '480p': {'resolution': '854x480', 'bitrate': '1200k', 'fps': '30'},
            '720p': {'resolution': '1280x720', 'bitrate': '2500k', 'fps': '30'},
            '1080p': {'resolution': '1920x1080', 'bitrate': '4500k', 'fps': '30'}
        }
        
        settings = quality_settings.get(quality, quality_settings['720p'])
        
        # FFmpeg command for YouTube streaming
        cmd = [
            'ffmpeg',
            '-re',  # Read input at native frame rate
            '-i', video_path,
            '-c:v', 'libx264',  # Video codec
            '-preset', 'veryfast',  # Encoding speed
            '-tune', 'zerolatency',  # Low latency
            '-b:v', settings['bitrate'],  # Video bitrate
            '-maxrate', settings['bitrate'],
            '-bufsize', str(int(settings['bitrate'].replace('k', '')) * 2) + 'k',
            '-s', settings['resolution'],  # Resolution
            '-r', settings['fps'],  # Frame rate
            '-g', '60',  # GOP size
            '-keyint_min', '60',
            '-sc_threshold', '0',
            '-c:a', 'aac',  # Audio codec
            '-b:a', '128k',  # Audio bitrate
            '-ar', '44100',  # Audio sample rate
            '-ac', '2',  # Audio channels
            '-f', 'flv',  # Output format
            f'rtmp://a.rtmp.youtube.com/live2/{streaming_key}'
        ]
        
        # Start FFmpeg process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        # Store process info
        if stream_index is not None:
            st.session_state.processes[stream_index] = process
            st.session_state.streams.loc[stream_index, 'PID'] = process.pid
            st.session_state.streams.loc[stream_index, 'Status'] = 'Sedang Live'
            save_persistent_streams(st.session_state.streams)
        
        # Auto-start YouTube broadcast if broadcast_id is provided
        if broadcast_id:
            def start_broadcast_delayed():
                time.sleep(8)  # Wait for stream to establish
                success, message = start_youtube_broadcast(broadcast_id, channel_name)
                if success:
                    print(f"✅ YouTube broadcast started: {message}")
                else:
                    print(f"❌ Failed to start YouTube broadcast: {message}")
            
            # Start broadcast in background thread
            threading.Thread(target=start_broadcast_delayed, daemon=True).start()
        
        # Monitor process
        def monitor_process():
            try:
                stdout, stderr = process.communicate()
                if stream_index is not None and stream_index in st.session_state.processes:
                    del st.session_state.processes[stream_index]
                    st.session_state.streams.loc[stream_index, 'Status'] = 'Selesai'
                    st.session_state.streams.loc[stream_index, 'PID'] = 0
                    save_persistent_streams(st.session_state.streams)
                    
                    # Auto-stop YouTube broadcast
                    if broadcast_id:
                        stop_youtube_broadcast(broadcast_id, channel_name)
                        
            except Exception as e:
                print(f"Error monitoring process: {e}")
        
        # Start monitoring in background thread
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
            
            # Get broadcast ID and channel for cleanup
            broadcast_id = st.session_state.streams.loc[stream_index, 'Broadcast ID']
            channel_name = st.session_state.streams.loc[stream_index, 'Channel']
            
            # Terminate FFmpeg process
            process.terminate()
            time.sleep(2)
            
            if process.poll() is None:
                process.kill()
            
            # Clean up
            del st.session_state.processes[stream_index]
            st.session_state.streams.loc[stream_index, 'Status'] = 'Dihentikan'
            st.session_state.streams.loc[stream_index, 'PID'] = 0
            save_persistent_streams(st.session_state.streams)
            
            # Stop YouTube broadcast
            if broadcast_id and broadcast_id != '':
                stop_youtube_broadcast(broadcast_id, channel_name)
            
            return True
    except Exception as e:
        st.error(f"Error stopping stream: {e}")
        return False

def check_scheduled_streams():
    """Check and start scheduled streams"""
    jakarta_time = get_jakarta_time()
    current_time = format_jakarta_time(jakarta_time)
    
    for idx, row in st.session_state.streams.iterrows():
        if row['Status'] == 'Menunggu':
            start_time = row['Jam Mulai']
            
            # Handle "NOW" case - start immediately
            if start_time == "NOW":
                quality = row.get('Quality', '720p')
                broadcast_id = row.get('Broadcast ID', None)
                channel_name = row.get('Channel', 'default')
                if start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), idx, quality, broadcast_id, channel_name):
                    st.session_state.streams.loc[idx, 'Jam Mulai'] = current_time
                    save_persistent_streams(st.session_state.streams)
                continue
            
            # Handle scheduled time
            try:
                # Parse scheduled time
                scheduled_parts = start_time.replace(' WIB', '').split(':')
                scheduled_hour = int(scheduled_parts[0])
                scheduled_minute = int(scheduled_parts[1])
                
                # Current time
                current_hour = jakarta_time.hour
                current_minute = jakarta_time.minute
                
                # Check if it's time to start
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

def calculate_time_difference(target_time_str):
    """Calculate time difference for display"""
    try:
        if target_time_str == "NOW":
            return "Starting now..."
        
        jakarta_time = get_jakarta_time()
        
        # Parse target time
        time_parts = target_time_str.replace(' WIB', '').split(':')
        target_hour = int(time_parts[0])
        target_minute = int(time_parts[1])
        
        # Create target datetime for today
        target_time = jakarta_time.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        
        # If target time has passed today, it's for tomorrow
        if target_time <= jakarta_time:
            target_time += datetime.timedelta(days=1)
        
        # Calculate difference
        time_diff = target_time - jakarta_time
        
        if time_diff.total_seconds() < 60:
            return "Starting soon..."
        elif time_diff.total_seconds() < 3600:
            minutes = int(time_diff.total_seconds() / 60)
            return f"Will start in {minutes} minutes"
        else:
            hours = int(time_diff.total_seconds() / 3600)
            minutes = int((time_diff.total_seconds() % 3600) / 60)
            return f"Will start in {hours}h {minutes}m"
            
    except Exception:
        return "Time calculation error"

# Streamlit UI
st.set_page_config(page_title="🎬 Multi-Channel YouTube Live Stream Manager", layout="wide")

st.title("🎬 Multi-Channel YouTube Live Stream Manager")
st.markdown("---")

# Auto-refresh for scheduled streams
check_scheduled_streams()

# Main tabs
tab1, tab2, tab3, tab4 = st.tabs(["📺 Stream Manager", "🔧 YouTube API Integration", "📊 Dashboard", "⚙️ Advanced Settings"])

with tab2:
    st.header("🔧 YouTube API Integration")
    
    # Instructions section
    with st.expander("📋 Setup Instructions", expanded=False):
        st.markdown("""
        ### 🚀 How to get YouTube API Credentials:
        
        1. **Go to Google Cloud Console**: Visit [Google Cloud Console](https://console.cloud.google.com/)
        2. **Create/Select Project**: Create a new project or select existing one
        3. **Enable YouTube API**: Go to "APIs & Services" → "Library" → Search "YouTube Data API v3" → Enable
        4. **Create Credentials**: Go to "APIs & Services" → "Credentials" → "Create Credentials" → "OAuth 2.0 Client IDs"
        5. **Configure OAuth**: Set application type to "Desktop application"
        6. **Download JSON**: Download the credentials file (credentials.json)
        7. **Upload Here**: Upload the file below with a descriptive channel name
        
        ### 📝 Important Notes:
        - Each channel needs its own credentials file
        - Use descriptive names like "main-channel", "gaming-channel", etc.
        - After upload, click "Authenticate" to complete setup
        """)
    
    # Upload credentials section
    st.subheader("📁 Add New Channel")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        channel_name = st.text_input(
            "📝 Channel Name", 
            placeholder="e.g., main-channel, gaming-channel, music-channel",
            help="Use descriptive names to identify your channels"
        )
        
        uploaded_file = st.file_uploader(
            "📤 Upload credentials.json", 
            type=['json'],
            help="Upload the Google API credentials file for this channel"
        )
        
        if uploaded_file and channel_name:
            # Validate the uploaded file
            file_content = uploaded_file.read().decode('utf-8')
            is_valid, message = validate_credentials_file(file_content)
            
            if is_valid:
                st.success(f"✅ {message}")
                
                if st.button("💾 Save Credentials", type="primary"):
                    try:
                        # Save credentials file
                        credentials_path = get_channel_credentials_path(channel_name)
                        with open(credentials_path, 'w') as f:
                            f.write(file_content)
                        
                        # Store in session state for authentication
                        st.session_state.uploaded_credentials[channel_name] = credentials_path
                        
                        st.success(f"✅ Credentials saved for channel '{channel_name}'")
                        st.info("👆 Now click the 'Authenticate' button to complete setup")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error saving credentials: {e}")
            else:
                st.error(f"❌ {message}")
    
    with col2:
        st.subheader("📊 Quick Stats")
        available_channels = get_available_channels()
        authenticated_channels = [ch for ch in available_channels if is_channel_authenticated(ch)]
        
        st.metric("📺 Total Channels", len(available_channels))
        st.metric("✅ Authenticated", len(authenticated_channels))
        st.metric("⚠️ Need Auth", len(available_channels) - len(authenticated_channels))
    
    # Channel management section
    st.subheader("📺 Manage Channels")
    
    available_channels = get_available_channels()
    
    if available_channels:
        # Bulk actions
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button("🔄 Refresh All"):
                st.rerun()
        
        with col2:
            if st.button("🧪 Test All Connections"):
                with st.spinner("Testing all connections..."):
                    for channel in available_channels:
                        if is_channel_authenticated(channel):
                            info = get_channel_info(channel)
                            if info:
                                st.success(f"✅ {channel}: Connected")
                            else:
                                st.error(f"❌ {channel}: Connection failed")
                        else:
                            st.warning(f"⚠️ {channel}: Not authenticated")
        
        # Individual channel cards
        for channel in available_channels:
            with st.container():
                # Create enhanced channel card
                card_col1, card_col2, card_col3 = st.columns([2, 2, 1])
                
                with card_col1:
                    st.write(f"### 📺 {channel}")
                    
                    # Check authentication status
                    is_auth = is_channel_authenticated(channel)
                    
                    if is_auth:
                        st.success("✅ Authenticated")
                        
                        # Get and display channel info
                        channel_info = get_channel_info(channel)
                        if channel_info:
                            st.write(f"**📊 {channel_info['title']}**")
                            st.caption(f"🆔 ID: {channel_info['id']}")
                            if channel_info['custom_url'] != 'N/A':
                                st.caption(f"🔗 URL: {channel_info['custom_url']}")
                        else:
                            st.warning("⚠️ Could not fetch channel info")
                    else:
                        st.error("❌ Not authenticated")
                        st.caption("Click 'Authenticate' to complete setup")
                
                with card_col2:
                    if is_auth:
                        channel_info = get_channel_info(channel)
                        if channel_info:
                            # Display metrics in a nice format
                            metric_col1, metric_col2 = st.columns(2)
                            
                            with metric_col1:
                                st.metric("👥 Subscribers", channel_info['subscribers'])
                                st.metric("🎥 Videos", channel_info['videos'])
                            
                            with metric_col2:
                                st.metric("👀 Views", channel_info['views'])
                                st.metric("🌍 Country", channel_info['country'])
                    else:
                        st.info("📝 Authenticate to see channel metrics")
                
                with card_col3:
                    # Action buttons
                    if not is_auth:
                        if st.button(f"🔐 Authenticate", key=f"auth_{channel}", type="primary"):
                            with st.spinner(f"Authenticating {channel}..."):
                                try:
                                    youtube_service, auth_message = authenticate_channel(channel)
                                    if youtube_service:
                                        st.success(f"✅ {auth_message}")
                                        st.rerun()
                                    else:
                                        st.error(f"❌ {auth_message}")
                                except Exception as e:
                                    st.error(f"❌ Authentication failed: {str(e)}")
                    else:
                        if st.button(f"🔄 Re-authenticate", key=f"reauth_{channel}"):
                            # Remove existing token to force re-authentication
                            token_path = get_channel_token_path(channel)
                            if os.path.exists(token_path):
                                os.remove(token_path)
                            
                            with st.spinner(f"Re-authenticating {channel}..."):
                                try:
                                    youtube_service, auth_message = authenticate_channel(channel)
                                    if youtube_service:
                                        st.success(f"✅ {auth_message}")
                                        st.rerun()
                                    else:
                                        st.error(f"❌ {auth_message}")
                                except Exception as e:
                                    st.error(f"❌ Re-authentication failed: {str(e)}")
                    
                    # Remove button
                    if st.button(f"🗑️ Remove", key=f"remove_{channel}"):
                        try:
                            # Remove credentials and token files
                            credentials_path = get_channel_credentials_path(channel)
                            token_path = get_channel_token_path(channel)
                            
                            if os.path.exists(credentials_path):
                                os.remove(credentials_path)
                            if os.path.exists(token_path):
                                os.remove(token_path)
                            
                            # Remove from session state
                            if channel in st.session_state.uploaded_credentials:
                                del st.session_state.uploaded_credentials[channel]
                            
                            st.success(f"✅ Channel '{channel}' removed")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error removing channel: {e}")
                
                st.markdown("---")
    else:
        st.info("📝 No channels configured. Upload credentials above to get started!")

with tab1:
    # Sidebar for YouTube Broadcast Creation
    with st.sidebar:
        st.header("📺 Create YouTube Broadcast")
        
        # Channel selection
        available_channels = get_available_channels()
        authenticated_channels = [ch for ch in available_channels if is_channel_authenticated(ch)]
        
        if not authenticated_channels:
            st.warning("⚠️ No authenticated channels available. Please authenticate channels first.")
        else:
            selected_channel = st.selectbox("📺 Select Channel", authenticated_channels)
            
            # Show channel info
            if selected_channel:
                channel_info = get_channel_info(selected_channel)
                if channel_info:
                    st.info(f"📊 **{channel_info['title']}**\n👥 {channel_info['subscribers']} subscribers")
            
            with st.form("broadcast_form"):
                title = st.text_input("🎬 Broadcast Title", value="Live Stream")
                description = st.text_area("📝 Description", value="Live streaming content")
                
                # Privacy settings
                privacy = st.selectbox("🔒 Privacy", ['public', 'unlisted', 'private'], index=0)
                
                # Time selection with Jakarta timezone
                jakarta_time = get_jakarta_time()
                current_time_str = format_jakarta_time(jakarta_time)
                
                st.write(f"🕐 Current Time: **{current_time_str}**")
                
                # Quick time buttons
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
                
                # Manual time input
                if not broadcast_time:
                    manual_time = st.time_input("🕐 Or set custom time", value=jakarta_time.time())
                    if st.form_submit_button("📅 Schedule"):
                        broadcast_time = manual_time
                
                # Process broadcast creation
                if broadcast_time and selected_channel:
                    with st.spinner(f"Creating YouTube broadcast on '{selected_channel}'..."):
                        # Format time for API
                        if start_immediately:
                            time_str = "NOW"
                        else:
                            time_str = broadcast_time.strftime('%H:%M')
                        
                        # Create broadcast
                        broadcast_id, stream_key, error = create_youtube_broadcast(
                            title, description, time_str, privacy, False, selected_channel
                        )
                        
                        if error:
                            st.error(f"❌ {error}")
                        else:
                            st.success(f"✅ Broadcast created successfully on '{selected_channel}'!")
                            st.info(f"🔑 Stream Key: `{stream_key}`")
                            st.info(f"🆔 Broadcast ID: `{broadcast_id}`")
                            
                            # Auto-add to stream manager
                            video_files = get_video_files()
                            if video_files:
                                selected_video = st.selectbox("📹 Select video to stream", video_files)
                                quality = st.selectbox("🎥 Quality", ['240p', '360p', '480p', '720p', '1080p'], index=3)
                                is_shorts = st.checkbox("📱 YouTube Shorts format")
                                
                                if st.button("➕ Add to Stream Manager"):
                                    # Add to streams
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
        st.header("📋 Stream Manager")
        
        # Add new stream form
        with st.expander("➕ Add New Stream", expanded=False):
            with st.form("add_stream"):
                video_files = get_video_files()
                authenticated_channels = [ch for ch in get_available_channels() if is_channel_authenticated(ch)]
                
                if not video_files:
                    st.warning("⚠️ No video files found in current directory")
                    st.stop()
                
                if not authenticated_channels:
                    st.warning("⚠️ No authenticated channels available. Please authenticate channels first.")
                    st.stop()
                
                selected_video = st.selectbox("📹 Select Video", video_files)
                selected_channel = st.selectbox("📺 Select Channel", authenticated_channels)
                streaming_key = st.text_input("🔑 Streaming Key", help="Your YouTube streaming key")
                
                # Time input with Jakarta timezone
                jakarta_time = get_jakarta_time()
                current_time_str = format_jakarta_time(jakarta_time)
                
                st.write(f"🕐 Current Time: **{current_time_str}**")
                
                # Quick time selection
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
                
                # Manual time input
                if not schedule_time:
                    manual_time = st.time_input("🕐 Or set custom time", value=jakarta_time.time())
                    quality = st.selectbox("🎥 Quality", ['240p', '360p', '480p', '720p', '1080p'], index=3)
                    is_shorts = st.checkbox("📱 YouTube Shorts format")
                    
                    if st.form_submit_button("📅 Add Stream"):
                        schedule_time = format_jakarta_time(
                            jakarta_time.replace(hour=manual_time.hour, minute=manual_time.minute, second=0, microsecond=0)
                        )
                
                # Process stream addition
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
                    # Create card-like layout
                    card_col1, card_col2, card_col3, card_col4 = st.columns([3, 2, 2, 2])
                    
                    with card_col1:
                        st.write(f"**📹 {row['Video']}**")
                        st.caption(f"📺 Channel: {row.get('Channel', 'default')} | Quality: {row.get('Quality', '720p')}")
                        
                        # YouTube link if broadcast ID exists
                        if row.get('Broadcast ID') and row['Broadcast ID'] != '':
                            youtube_url = f"https://youtube.com/watch?v={row['Broadcast ID']}"
                            st.markdown(f"🔗 [Watch on YouTube]({youtube_url})")
                        
                        st.caption(f"Key: {row['Streaming Key'][:8]}****")
                    
                    with card_col2:
                        # Time display with countdown
                        st.write(f"🕐 **{row['Jam Mulai']}**")
                        if row['Status'] == 'Menunggu':
                            time_info = calculate_time_difference(row['Jam Mulai'])
                            st.caption(time_info)
                    
                    with card_col3:
                        # Status with colored indicators
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
                        # Action buttons
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
                        
                        # Delete button
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
        
        # Current time
        jakarta_time = get_jakarta_time()
        st.metric("🕐 Current Time", format_jakarta_time(jakarta_time))
        
        # Active streams count
        active_streams = len(st.session_state.streams[st.session_state.streams['Status'] == 'Sedang Live'])
        st.metric("📺 Active Streams", active_streams)
        
        # Waiting streams count
        waiting_streams = len(st.session_state.streams[st.session_state.streams['Status'] == 'Menunggu'])
        st.metric("⏳ Waiting Streams", waiting_streams)
        
        # Channels count
        available_channels = get_available_channels()
        authenticated_channels = [ch for ch in available_channels if is_channel_authenticated(ch)]
        st.metric("📺 Authenticated Channels", len(authenticated_channels))
        
        # System resources
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            
            st.metric("💻 CPU Usage", f"{cpu_percent:.1f}%")
            st.metric("🧠 Memory Usage", f"{memory.percent:.1f}%")
        except:
            st.info("System monitoring unavailable")
        
        # Auto-refresh
        if st.button("🔄 Refresh Status"):
            st.rerun()

with tab3:
    st.header("📊 Multi-Channel Dashboard")
    
    available_channels = get_available_channels()
    authenticated_channels = [ch for ch in available_channels if is_channel_authenticated(ch)]
    
    if authenticated_channels:
        # Overall statistics
        st.subheader("📈 Overall Statistics")
        
        total_subscribers = 0
        total_videos = 0
        total_views = 0
        
        col1, col2, col3, col4 = st.columns(4)
        
        # Calculate totals
        for channel in authenticated_channels:
            channel_info = get_channel_info(channel)
            if channel_info:
                try:
                    total_subscribers += int(channel_info['subscribers']) if channel_info['subscribers'] != 'N/A' else 0
                    total_videos += int(channel_info['videos']) if channel_info['videos'] != 'N/A' else 0
                    total_views += int(channel_info['views']) if channel_info['views'] != 'N/A' else 0
                except:
                    pass
        
        with col1:
            st.metric("📺 Total Channels", len(authenticated_channels))
        with col2:
            st.metric("👥 Total Subscribers", f"{total_subscribers:,}")
        with col3:
            st.metric("🎥 Total Videos", f"{total_videos:,}")
        with col4:
            st.metric("👀 Total Views", f"{total_views:,}")
        
        # Channel overview
        st.subheader("📺 Channel Overview")
        
        for channel in authenticated_channels:
            with st.expander(f"📺 {channel}", expanded=True):
                col1, col2, col3 = st.columns(3)
                
                # Get channel info
                channel_info = get_channel_info(channel)
                
                with col1:
                    if channel_info:
                        st.metric("📊 Channel", channel_info['title'])
                        st.metric("👥 Subscribers", channel_info['subscribers'])
                        st.metric("🎥 Videos", channel_info['videos'])
                    else:
                        st.warning("⚠️ Could not fetch channel info")
                
                with col2:
                    # Active streams for this channel
                    channel_streams = st.session_state.streams[st.session_state.streams['Channel'] == channel]
                    active_count = len(channel_streams[channel_streams['Status'] == 'Sedang Live'])
                    waiting_count = len(channel_streams[channel_streams['Status'] == 'Menunggu'])
                    
                    st.metric("🟢 Active Streams", active_count)
                    st.metric("🟡 Waiting Streams", waiting_count)
                    st.metric("📊 Total Streams", len(channel_streams))
                
                with col3:
                    if channel_info:
                        st.metric("👀 Total Views", channel_info['views'])
                        st.metric("🌍 Country", channel_info['country'])
                    
                    # Quick actions
                    if st.button(f"🔄 Refresh {channel}", key=f"refresh_{channel}"):
                        st.rerun()
        
        # Analytics charts
        if not st.session_state.streams.empty:
            st.subheader("📈 Stream Analytics")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**📊 Streams by Channel**")
                channel_counts = st.session_state.streams['Channel'].value_counts()
                st.bar_chart(channel_counts)
            
            with col2:
                st.write("**📊 Streams by Status**")
                status_counts = st.session_state.streams['Status'].value_counts()
                st.bar_chart(status_counts)
            
            # Quality distribution
            st.write("**🎥 Quality Distribution**")
            quality_counts = st.session_state.streams['Quality'].value_counts()
            st.bar_chart(quality_counts)
    
    else:
        st.info("📝 No authenticated channels available. Please authenticate channels in the YouTube API Integration tab.")

with tab4:
    st.header("⚙️ Advanced Settings")
    
    # Application settings
    st.subheader("🔧 Application Settings")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("**⏱️ Auto-refresh Settings**")
        auto_refresh = st.checkbox("Enable auto-refresh", value=True)
        refresh_interval = st.slider("Refresh interval (seconds)", 5, 60, 10)
        
        st.write("**🎥 Default Settings**")
        default_quality = st.selectbox("Default quality", ['240p', '360p', '480p', '720p', '1080p'], index=3)
        default_privacy = st.selectbox("Default privacy", ['public', 'unlisted', 'private'], index=0)
    
    with col2:
        st.write("**📊 System Information**")
        st.info(f"📁 Credentials files: {len([f for f in os.listdir('.') if f.startswith('credentials_')])}")
        st.info(f"🔑 Token files: {len([f for f in os.listdir('.') if f.startswith('token_')])}")
        st.info(f"📺 Available channels: {len(get_available_channels())}")
        st.info(f"✅ Authenticated channels: {len([ch for ch in get_available_channels() if is_channel_authenticated(ch)])}")
        st.info(f"📊 Total streams: {len(st.session_state.streams)}")
    
    # Data management
    st.subheader("💾 Data Management")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📤 Export Stream Data"):
            try:
                st.session_state.streams.to_csv('exported_streams.csv', index=False)
                st.success("✅ Stream data exported to 'exported_streams.csv'")
            except Exception as e:
                st.error(f"❌ Export failed: {e}")
    
    with col2:
        uploaded_streams = st.file_uploader("📥 Import Stream Data", type=['csv'])
        if uploaded_streams:
            try:
                imported_df = pd.read_csv(uploaded_streams)
                st.session_state.streams = imported_df
                save_persistent_streams(st.session_state.streams)
                st.success("✅ Stream data imported successfully")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Import failed: {e}")
    
    with col3:
        if st.button("🗑️ Clear All Stream Data", type="secondary"):
            if st.checkbox("⚠️ I understand this will delete all stream data"):
                st.session_state.streams = pd.DataFrame(columns=[
                    'Video', 'Streaming Key', 'Jam Mulai', 'Status', 'PID', 'Is Shorts', 'Quality', 'Broadcast ID', 'Channel'
                ])
                save_persistent_streams(st.session_state.streams)
                st.success("✅ All stream data cleared")
                st.rerun()
    
    # File management
    st.subheader("📁 File Management")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("**📹 Video Files**")
        video_files = get_video_files()
        if video_files:
            for video in video_files[:5]:  # Show first 5
                st.text(f"📹 {video}")
            if len(video_files) > 5:
                st.caption(f"... and {len(video_files) - 5} more")
        else:
            st.info("No video files found")
    
    with col2:
        st.write("**🔧 Configuration Files**")
        config_files = [f for f in os.listdir('.') if f.endswith('.json') or f.endswith('.csv')]
        for config in config_files:
            st.text(f"📄 {config}")

# Footer
st.markdown("---")
st.markdown("🎬 **Multi-Channel YouTube Live Stream Manager** - Manage multiple YouTube channels with automated streaming")
