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
    """Validate uploaded credentials file"""
    try:
        credentials_data = json.loads(file_content)
        
        # Check if it's a valid Google API credentials file
        if 'installed' in credentials_data:
            required_fields = ['client_id', 'client_secret', 'auth_uri', 'token_uri']
            installed = credentials_data['installed']
            
            for field in required_fields:
                if field not in installed:
                    return False, f"Missing required field: {field}"
            
            return True, "Valid credentials file"
        
        elif 'web' in credentials_data:
            required_fields = ['client_id', 'client_secret', 'auth_uri', 'token_uri']
            web = credentials_data['web']
            
            for field in required_fields:
                if field not in web:
                    return False, f"Missing required field: {field}"
            
            return True, "Valid credentials file"
        
        else:
            return False, "Invalid credentials format. Must contain 'installed' or 'web' configuration."
    
    except json.JSONDecodeError:
        return False, "Invalid JSON format"
    except Exception as e:
        return False, f"Validation error: {str(e)}"

def get_youtube_service(channel_name='default'):
    """Get authenticated YouTube service for specific channel"""
    creds = None
    token_path = get_channel_token_path(channel_name)
    credentials_path = get_channel_credentials_path(channel_name)
    
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            st.warning(f"Token file corrupted for {channel_name}, will re-authenticate")
            if os.path.exists(token_path):
                os.remove(token_path)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                st.warning(f"Token refresh failed for {channel_name}, will re-authenticate")
                creds = None
        
        if not creds:
            if os.path.exists(credentials_path):
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                    creds = flow.run_local_server(port=0, open_browser=False)
                    st.success(f"✅ Successfully authenticated channel '{channel_name}'")
                except Exception as e:
                    st.error(f"❌ Authentication failed for channel '{channel_name}': {str(e)}")
                    return None
            else:
                st.error(f"❌ Credentials file not found for channel '{channel_name}'. Please upload credentials first.")
                return None
        
        # Save credentials
        try:
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            st.warning(f"Could not save token for {channel_name}: {str(e)}")
    
    try:
        return build('youtube', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"❌ Failed to build YouTube service for channel '{channel_name}': {str(e)}")
        return None

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
                'description': channel['snippet'].get('description', '')[:100] + '...' if channel['snippet'].get('description') else '',
                'subscribers': channel['statistics'].get('subscriberCount', 'N/A'),
                'videos': channel['statistics'].get('videoCount', 'N/A'),
                'views': channel['statistics'].get('viewCount', 'N/A'),
                'thumbnail': channel['snippet']['thumbnails'].get('default', {}).get('url', ''),
                'country': channel['snippet'].get('country', 'N/A'),
                'created_date': channel['snippet'].get('publishedAt', 'N/A')
            }
        return None
    except Exception as e:
        st.error(f"Error getting channel info for {channel_name}: {e}")
        return None

def test_channel_connection(channel_name):
    """Test YouTube API connection for a channel"""
    try:
        youtube = get_youtube_service(channel_name)
        if not youtube:
            return False, "Failed to get YouTube service"
        
        # Try to get channel info
        response = youtube.channels().list(
            part='snippet',
            mine=True
        ).execute()
        
        if response['items']:
            channel_title = response['items'][0]['snippet']['title']
            return True, f"Connected to: {channel_title}"
        else:
            return False, "No channel found"
    
    except HttpError as e:
        return False, f"API Error: {e.error_details[0].get('message', str(e)) if e.error_details else str(e)}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"

def create_youtube_broadcast(title, description, start_time_str, privacy_status='public', is_shorts=False, channel_name='default'):
    """Create YouTube live broadcast with proper time synchronization"""
    try:
        youtube = get_youtube_service(channel_name)
        if not youtube:
            return None, None, f"YouTube service not available for channel '{channel_name}'"
        
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

def export_channel_data():
    """Export all channel data"""
    try:
        export_data = {
            'channels': {},
            'streams': st.session_state.streams.to_dict('records') if not st.session_state.streams.empty else [],
            'export_date': datetime.datetime.now().isoformat()
        }
        
        # Get channel info for each available channel
        for channel in get_available_channels():
            channel_info = get_channel_info(channel)
            if channel_info:
                export_data['channels'][channel] = channel_info
        
        return json.dumps(export_data, indent=2)
    except Exception as e:
        st.error(f"Error exporting data: {e}")
        return None

def bulk_channel_operations(channels, operation):
    """Perform bulk operations on multiple channels"""
    results = {}
    
    for channel in channels:
        try:
            if operation == 'test_connection':
                success, message = test_channel_connection(channel)
                results[channel] = {'success': success, 'message': message}
            elif operation == 'get_info':
                info = get_channel_info(channel)
                results[channel] = {'success': info is not None, 'data': info}
        except Exception as e:
            results[channel] = {'success': False, 'message': str(e)}
    
    return results

# Initialize session state
if 'streams' not in st.session_state:
    st.session_state.streams = pd.DataFrame(columns=[
        'Video', 'Streaming Key', 'Jam Mulai', 'Status', 'PID', 'Is Shorts', 'Quality', 'Broadcast ID', 'Channel'
    ])

if 'processes' not in st.session_state:
    st.session_state.processes = {}

if 'channel_configs' not in st.session_state:
    st.session_state.channel_configs = load_channel_config()

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
st.set_page_config(page_title="🎬 Enhanced Multi-Channel YouTube Live Stream Manager", layout="wide")

st.title("🎬 Enhanced Multi-Channel YouTube Live Stream Manager")
st.markdown("---")

# Auto-refresh for scheduled streams
check_scheduled_streams()

# Enhanced Tab Layout
tab1, tab2, tab3, tab4 = st.tabs(["📺 Stream Manager", "🔧 YouTube API Integration", "📊 Multi-Channel Dashboard", "⚙️ Advanced Settings"])

with tab2:
    st.header("🔧 YouTube API Integration & Channel Management")
    
    # Quick Stats
    available_channels = get_available_channels()
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📺 Total Channels", len(available_channels))
    with col2:
        authenticated_count = sum(1 for ch in available_channels if get_channel_info(ch) is not None)
        st.metric("✅ Authenticated", authenticated_count)
    with col3:
        active_streams = len(st.session_state.streams[st.session_state.streams['Status'] == 'Sedang Live'])
        st.metric("🔴 Live Streams", active_streams)
    with col4:
        waiting_streams = len(st.session_state.streams[st.session_state.streams['Status'] == 'Menunggu'])
        st.metric("⏳ Scheduled", waiting_streams)
    
    st.markdown("---")
    
    # Channel Management Section
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        st.subheader("📁 Add New Channel")
        
        with st.form("add_channel_form"):
            st.markdown("**Step 1: Channel Information**")
            channel_name = st.text_input(
                "📝 Channel Name", 
                placeholder="e.g., main-channel, gaming-channel, music-channel",
                help="Use descriptive names to easily identify your channels"
            )
            
            channel_description = st.text_area(
                "📄 Channel Description (Optional)",
                placeholder="Brief description of this channel's purpose",
                height=80
            )
            
            st.markdown("**Step 2: Upload Credentials**")
            uploaded_file = st.file_uploader(
                "📤 Upload credentials.json", 
                type=['json'],
                help="Download this file from Google Cloud Console > APIs & Services > Credentials"
            )
            
            if uploaded_file:
                # Validate file
                file_content = uploaded_file.read().decode('utf-8')
                is_valid, validation_message = validate_credentials_file(file_content)
                
                if is_valid:
                    st.success(f"✅ {validation_message}")
                else:
                    st.error(f"❌ {validation_message}")
            
            # Submit button
            submit_button = st.form_submit_button("💾 Add Channel", use_container_width=True)
            
            if submit_button and channel_name and uploaded_file:
                if is_valid:
                    try:
                        # Save credentials file
                        credentials_path = get_channel_credentials_path(channel_name)
                        with open(credentials_path, 'w') as f:
                            f.write(file_content)
                        
                        # Save channel config
                        if 'channel_configs' not in st.session_state:
                            st.session_state.channel_configs = {}
                        
                        st.session_state.channel_configs[channel_name] = {
                            'description': channel_description,
                            'added_date': datetime.datetime.now().isoformat(),
                            'status': 'added'
                        }
                        save_channel_config()
                        
                        st.success(f"✅ Channel '{channel_name}' added successfully!")
                        st.info("🔄 Refreshing page to authenticate...")
                        time.sleep(2)
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Error saving channel: {e}")
                else:
                    st.error("❌ Please upload a valid credentials file")
            elif submit_button:
                st.warning("⚠️ Please fill in all required fields")
    
    with col_right:
        st.subheader("📋 Channel Management")
        
        if available_channels:
            # Bulk operations
            st.markdown("**Bulk Operations**")
            col_bulk1, col_bulk2, col_bulk3 = st.columns(3)
            
            with col_bulk1:
                if st.button("🔄 Test All Connections", use_container_width=True):
                    with st.spinner("Testing connections..."):
                        results = bulk_channel_operations(available_channels, 'test_connection')
                        for channel, result in results.items():
                            if result['success']:
                                st.success(f"✅ {channel}: {result['message']}")
                            else:
                                st.error(f"❌ {channel}: {result['message']}")
            
            with col_bulk2:
                if st.button("📊 Refresh All Info", use_container_width=True):
                    with st.spinner("Refreshing channel info..."):
                        results = bulk_channel_operations(available_channels, 'get_info')
                        success_count = sum(1 for r in results.values() if r['success'])
                        st.info(f"📊 Updated {success_count}/{len(available_channels)} channels")
            
            with col_bulk3:
                export_data = export_channel_data()
                if export_data:
                    st.download_button(
                        "📥 Export All Data",
                        data=export_data,
                        file_name=f"youtube_channels_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json",
                        use_container_width=True
                    )
            
            st.markdown("---")
            
            # Individual channel management
            for channel in available_channels:
                with st.expander(f"📺 {channel}", expanded=False):
                    col_info, col_actions = st.columns([2, 1])
                    
                    with col_info:
                        # Get channel info
                        channel_info = get_channel_info(channel)
                        
                        if channel_info:
                            st.markdown(f"**📊 {channel_info['title']}**")
                            
                            # Channel metrics
                            metric_col1, metric_col2, metric_col3 = st.columns(3)
                            with metric_col1:
                                st.metric("👥 Subscribers", channel_info['subscribers'])
                            with metric_col2:
                                st.metric("🎥 Videos", channel_info['videos'])
                            with metric_col3:
                                st.metric("👁️ Views", channel_info['views'])
                            
                            # Additional info
                            if channel_info.get('country') != 'N/A':
                                st.caption(f"🌍 Country: {channel_info['country']}")
                            
                            if channel_info.get('description'):
                                st.caption(f"📝 {channel_info['description']}")
                            
                            # Channel streams
                            channel_streams = st.session_state.streams[st.session_state.streams['Channel'] == channel]
                            if not channel_streams.empty:
                                st.caption(f"📺 Active Streams: {len(channel_streams[channel_streams['Status'] == 'Sedang Live'])}")
                                st.caption(f"⏳ Scheduled: {len(channel_streams[channel_streams['Status'] == 'Menunggu'])}")
                        
                        else:
                            st.warning("⚠️ Not authenticated or connection failed")
                            
                            # Test connection button
                            if st.button(f"🔄 Test Connection", key=f"test_{channel}"):
                                success, message = test_channel_connection(channel)
                                if success:
                                    st.success(f"✅ {message}")
                                    st.rerun()
                                else:
                                    st.error(f"❌ {message}")
                    
                    with col_actions:
                        st.markdown("**Actions**")
                        
                        # Re-authenticate button
                        if st.button(f"🔐 Re-auth", key=f"reauth_{channel}", use_container_width=True):
                            # Remove token file to force re-authentication
                            token_path = get_channel_token_path(channel)
                            if os.path.exists(token_path):
                                os.remove(token_path)
                            st.info("🔄 Token cleared. Will re-authenticate on next use.")
                            st.rerun()
                        
                        # Remove channel button
                        if st.button(f"🗑️ Remove", key=f"remove_{channel}", use_container_width=True):
                            try:
                                # Remove credentials and token files
                                credentials_path = get_channel_credentials_path(channel)
                                token_path = get_channel_token_path(channel)
                                
                                if os.path.exists(credentials_path):
                                    os.remove(credentials_path)
                                if os.path.exists(token_path):
                                    os.remove(token_path)
                                
                                # Remove from config
                                if channel in st.session_state.channel_configs:
                                    del st.session_state.channel_configs[channel]
                                    save_channel_config()
                                
                                st.success(f"✅ Channel '{channel}' removed")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error removing channel: {e}")
        
        else:
            st.info("📝 No channels configured. Add your first channel to get started!")
            
            # Quick setup guide
            with st.expander("📚 Quick Setup Guide", expanded=True):
                st.markdown("""
                **How to get YouTube API credentials:**
                
                1. 🌐 Go to [Google Cloud Console](https://console.cloud.google.com/)
                2. 📁 Create a new project or select existing one
                3. 🔧 Enable YouTube Data API v3
                4. 🔑 Create credentials (OAuth 2.0 Client ID)
                5. 📥 Download the credentials.json file
                6. 📤 Upload it here with a descriptive channel name
                
                **Tips:**
                - Use descriptive names like 'gaming-channel', 'music-channel'
                - Each channel needs its own credentials file
                - Keep your credentials secure and don't share them
                """)

with tab1:
    # Sidebar for YouTube Broadcast Creation
    with st.sidebar:
        st.header("📺 Create YouTube Broadcast")
        
        # Channel selection
        available_channels = get_available_channels()
        if not available_channels:
            st.warning("⚠️ No channels available. Please configure channels first.")
        else:
            selected_channel = st.selectbox("📺 Select Channel", available_channels)
            
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
                available_channels = get_available_channels()
                
                if not video_files:
                    st.warning("⚠️ No video files found in current directory")
                    st.stop()
                
                if not available_channels:
                    st.warning("⚠️ No channels available. Please configure channels first.")
                    st.stop()
                
                selected_video = st.selectbox("📹 Select Video", video_files)
                selected_channel = st.selectbox("📺 Select Channel", available_channels)
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
        st.metric("📺 Available Channels", len(available_channels))
        
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
    st.header("📊 Enhanced Multi-Channel Dashboard")
    
    available_channels = get_available_channels()
    
    if available_channels:
        # Overall statistics
        st.subheader("📈 Overall Statistics")
        
        total_subscribers = 0
        total_videos = 0
        total_views = 0
        authenticated_channels = 0
        
        for channel in available_channels:
            channel_info = get_channel_info(channel)
            if channel_info:
                authenticated_channels += 1
                try:
                    total_subscribers += int(channel_info['subscribers']) if channel_info['subscribers'] != 'N/A' else 0
                    total_videos += int(channel_info['videos']) if channel_info['videos'] != 'N/A' else 0
                    total_views += int(channel_info['views']) if channel_info['views'] != 'N/A' else 0
                except:
                    pass
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📺 Total Channels", len(available_channels))
        with col2:
            st.metric("✅ Authenticated", authenticated_channels)
        with col3:
            st.metric("👥 Total Subscribers", f"{total_subscribers:,}")
        with col4:
            st.metric("🎥 Total Videos", f"{total_videos:,}")
        
        st.markdown("---")
        
        # Channel overview
        st.subheader("📺 Channel Overview")
        
        for channel in available_channels:
            with st.expander(f"📺 {channel}", expanded=True):
                col1, col2, col3 = st.columns(3)
                
                # Get channel info
                channel_info = get_channel_info(channel)
                
                with col1:
                    if channel_info:
                        st.metric("📊 Channel", channel_info['title'])
                        st.metric("👥 Subscribers", channel_info['subscribers'])
                        st.metric("👁️ Views", channel_info['views'])
                    else:
                        st.warning("⚠️ Not authenticated")
                
                with col2:
                    # Active streams for this channel
                    channel_streams = st.session_state.streams[st.session_state.streams['Channel'] == channel]
                    active_count = len(channel_streams[channel_streams['Status'] == 'Sedang Live'])
                    waiting_count = len(channel_streams[channel_streams['Status'] == 'Menunggu'])
                    total_streams = len(channel_streams)
                    
                    st.metric("🟢 Active Streams", active_count)
                    st.metric("🟡 Waiting Streams", waiting_count)
                    st.metric("📊 Total Streams", total_streams)
                
                with col3:
                    if channel_info:
                        st.metric("🎥 Total Videos", channel_info['videos'])
                        if channel_info.get('country') != 'N/A':
                            st.metric("🌍 Country", channel_info['country'])
                    
                    # Quick actions
                    if st.button(f"🔄 Refresh {channel}", key=f"refresh_{channel}"):
                        st.rerun()
        
        # Stream distribution charts
        if not st.session_state.streams.empty:
            st.subheader("📈 Analytics & Charts")
            
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                st.markdown("**Stream Distribution by Channel**")
                channel_counts = st.session_state.streams['Channel'].value_counts()
                st.bar_chart(channel_counts)
            
            with col_chart2:
                st.markdown("**Stream Status Distribution**")
                status_counts = st.session_state.streams['Status'].value_counts()
                st.bar_chart(status_counts)
            
            # Quality distribution
            st.markdown("**Quality Distribution**")
            quality_counts = st.session_state.streams['Quality'].value_counts()
            st.bar_chart(quality_counts)
    
    else:
        st.info("📝 No channels configured. Please add channels in the YouTube API Integration tab.")

with tab4:
    st.header("⚙️ Advanced Settings & Tools")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🔧 System Configuration")
        
        # Auto-refresh settings
        auto_refresh = st.checkbox("🔄 Auto-refresh dashboard", value=True)
        if auto_refresh:
            refresh_interval = st.slider("Refresh interval (seconds)", 5, 60, 10)
        
        # Default quality setting
        default_quality = st.selectbox("🎥 Default Stream Quality", ['240p', '360p', '480p', '720p', '1080p'], index=3)
        
        # Default privacy setting
        default_privacy = st.selectbox("🔒 Default Broadcast Privacy", ['public', 'unlisted', 'private'], index=0)
        
        # Save settings
        if st.button("💾 Save Settings"):
            settings = {
                'auto_refresh': auto_refresh,
                'refresh_interval': refresh_interval if auto_refresh else 10,
                'default_quality': default_quality,
                'default_privacy': default_privacy
            }
            
            with open('app_settings.json', 'w') as f:
                json.dump(settings, f, indent=2)
            
            st.success("✅ Settings saved!")
    
    with col2:
        st.subheader("📊 Data Management")
        
        # Export data
        st.markdown("**Export Data**")
        export_data = export_channel_data()
        if export_data:
            st.download_button(
                "📥 Export All Data (JSON)",
                data=export_data,
                file_name=f"youtube_manager_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )
        
        # Clear data
        st.markdown("**Clear Data**")
        if st.button("🗑️ Clear All Streams", type="secondary"):
            if st.checkbox("⚠️ I understand this will delete all stream data"):
                st.session_state.streams = pd.DataFrame(columns=['Video', 'Streaming Key', 'Jam Mulai', 'Status', 'PID', 'Is Shorts', 'Quality', 'Broadcast ID', 'Channel'])
                save_persistent_streams(st.session_state.streams)
                st.success("✅ All streams cleared!")
                st.rerun()
        
        # System info
        st.markdown("**System Information**")
        st.info(f"""
        📁 Video files: {len(get_video_files())}
        📺 Configured channels: {len(get_available_channels())}
        🔴 Active streams: {len(st.session_state.streams[st.session_state.streams['Status'] == 'Sedang Live'])}
        ⏳ Scheduled streams: {len(st.session_state.streams[st.session_state.streams['Status'] == 'Menunggu'])}
        """)

# Footer
st.markdown("---")
st.markdown("🎬 **Enhanced Multi-Channel YouTube Live Stream Manager** - Professional YouTube channel management with advanced API integration")
