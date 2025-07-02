import sys
import subprocess
import threading
import time
import os
import streamlit.components.v1 as components
import shutil
import datetime
import pandas as pd
import json
import signal
import psutil
import requests
from urllib.parse import urlencode
import base64

# Install required packages if not already installed
try:
    import streamlit as st
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "streamlit"])
    import streamlit as st

try:
    import google.auth
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-auth", "google-auth-oauthlib", "google-auth-httplib2", "google-api-python-client"])
    import google.auth
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

# Persistent storage files
STREAMS_FILE = "streams_data.json"
ACTIVE_STREAMS_FILE = "active_streams.json"
TEMPLATES_FILE = "stream_templates.json"
ANALYTICS_FILE = "analytics_data.json"
YOUTUBE_CREDENTIALS_FILE = "youtube_credentials.json"
YOUTUBE_CONFIG_FILE = "youtube_config.json"

# YouTube API Configuration
YOUTUBE_SCOPES = [
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.force-ssl'
]

def load_youtube_config():
    """Load YouTube API configuration"""
    if os.path.exists(YOUTUBE_CONFIG_FILE):
        try:
            with open(YOUTUBE_CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_youtube_config(config):
    """Save YouTube API configuration"""
    try:
        with open(YOUTUBE_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        st.error(f"Error saving YouTube config: {e}")

def load_youtube_credentials():
    """Load YouTube API credentials"""
    if os.path.exists(YOUTUBE_CREDENTIALS_FILE):
        try:
            with open(YOUTUBE_CREDENTIALS_FILE, "r") as f:
                creds_data = json.load(f)
                return Credentials.from_authorized_user_info(creds_data, YOUTUBE_SCOPES)
        except:
            return None
    return None

def save_youtube_credentials(credentials):
    """Save YouTube API credentials"""
    try:
        creds_data = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        with open(YOUTUBE_CREDENTIALS_FILE, "w") as f:
            json.dump(creds_data, f, indent=2)
    except Exception as e:
        st.error(f"Error saving credentials: {e}")

def get_youtube_service():
    """Get authenticated YouTube service"""
    credentials = load_youtube_credentials()
    
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                save_youtube_credentials(credentials)
            except Exception as e:
                st.error(f"Error refreshing credentials: {e}")
                return None
        else:
            return None
    
    try:
        return build('youtube', 'v3', credentials=credentials)
    except Exception as e:
        st.error(f"Error building YouTube service: {e}")
        return None

def create_youtube_live_broadcast(youtube, title, description, scheduled_start_time, privacy_status='unlisted'):
    """Create a YouTube Live broadcast"""
    try:
        # Create broadcast
        broadcast_response = youtube.liveBroadcasts().insert(
            part='snippet,status',
            body={
                'snippet': {
                    'title': title,
                    'description': description,
                    'scheduledStartTime': scheduled_start_time.isoformat() + 'Z'
                },
                'status': {
                    'privacyStatus': privacy_status,
                    'selfDeclaredMadeForKids': False
                }
            }
        ).execute()
        
        broadcast_id = broadcast_response['id']
        
        # Create stream
        stream_response = youtube.liveStreams().insert(
            part='snippet,cdn',
            body={
                'snippet': {
                    'title': f'Stream for {title}'
                },
                'cdn': {
                    'format': '1080p',
                    'ingestionType': 'rtmp'
                }
            }
        ).execute()
        
        stream_id = stream_response['id']
        stream_key = stream_response['cdn']['ingestionInfo']['streamName']
        rtmp_url = stream_response['cdn']['ingestionInfo']['ingestionAddress']
        
        # Bind stream to broadcast
        youtube.liveBroadcasts().bind(
            part='id',
            id=broadcast_id,
            streamId=stream_id
        ).execute()
        
        return {
            'broadcast_id': broadcast_id,
            'stream_id': stream_id,
            'stream_key': stream_key,
            'rtmp_url': rtmp_url,
            'watch_url': f'https://www.youtube.com/watch?v={broadcast_id}'
        }
        
    except HttpError as e:
        st.error(f"YouTube API Error: {e}")
        return None
    except Exception as e:
        st.error(f"Error creating broadcast: {e}")
        return None

def update_youtube_broadcast_status(youtube, broadcast_id, status):
    """Update YouTube broadcast status (testing, live, complete)"""
    try:
        youtube.liveBroadcasts().transition(
            part='status',
            id=broadcast_id,
            broadcastStatus=status
        ).execute()
        return True
    except Exception as e:
        st.error(f"Error updating broadcast status: {e}")
        return False

def get_youtube_channel_info(youtube):
    """Get YouTube channel information"""
    try:
        response = youtube.channels().list(
            part='snippet,statistics',
            mine=True
        ).execute()
        
        if response['items']:
            channel = response['items'][0]
            return {
                'id': channel['id'],
                'title': channel['snippet']['title'],
                'description': channel['snippet']['description'],
                'subscriber_count': channel['statistics'].get('subscriberCount', 'Hidden'),
                'video_count': channel['statistics']['videoCount'],
                'view_count': channel['statistics']['viewCount']
            }
    except Exception as e:
        st.error(f"Error getting channel info: {e}")
    return None

def get_youtube_live_broadcasts(youtube, max_results=10):
    """Get list of YouTube live broadcasts"""
    try:
        response = youtube.liveBroadcasts().list(
            part='snippet,status',
            mine=True,
            maxResults=max_results,
            order='date'
        ).execute()
        
        broadcasts = []
        for item in response.get('items', []):
            broadcasts.append({
                'id': item['id'],
                'title': item['snippet']['title'],
                'description': item['snippet']['description'],
                'scheduled_start_time': item['snippet'].get('scheduledStartTime'),
                'actual_start_time': item['snippet'].get('actualStartTime'),
                'status': item['status']['lifeCycleStatus'],
                'privacy_status': item['status']['privacyStatus'],
                'watch_url': f'https://www.youtube.com/watch?v={item["id"]}'
            })
        
        return broadcasts
    except Exception as e:
        st.error(f"Error getting broadcasts: {e}")
        return []

def auto_create_youtube_stream(title, description, scheduled_time, privacy_status='unlisted'):
    """Automatically create YouTube stream and return stream key"""
    youtube = get_youtube_service()
    if not youtube:
        return None
    
    broadcast_info = create_youtube_live_broadcast(
        youtube, title, description, scheduled_time, privacy_status
    )
    
    if broadcast_info:
        return {
            'stream_key': broadcast_info['stream_key'],
            'broadcast_id': broadcast_info['broadcast_id'],
            'watch_url': broadcast_info['watch_url'],
            'rtmp_url': broadcast_info['rtmp_url']
        }
    
    return None

def load_persistent_streams():
    """Load streams from persistent storage"""
    if os.path.exists(STREAMS_FILE):
        try:
            with open(STREAMS_FILE, "r") as f:
                data = json.load(f)
                return pd.DataFrame(data)
        except:
            return pd.DataFrame(columns=[
                'Video', 'Durasi', 'Jam Mulai', 'Streaming Key', 'Status', 'Is Shorts', 'Quality',
                'YouTube Broadcast ID', 'YouTube Watch URL', 'Auto Created', 'Stream Title', 'Stream Description'
            ])
    return pd.DataFrame(columns=[
        'Video', 'Durasi', 'Jam Mulai', 'Streaming Key', 'Status', 'Is Shorts', 'Quality',
        'YouTube Broadcast ID', 'YouTube Watch URL', 'Auto Created', 'Stream Title', 'Stream Description'
    ])

def save_persistent_streams(streams_df):
    """Save streams to persistent storage"""
    try:
        with open(STREAMS_FILE, "w") as f:
            json.dump(streams_df.to_dict('records'), f, indent=2)
    except Exception as e:
        st.error(f"Error saving streams: {e}")

def load_active_streams():
    """Load active streams tracking"""
    if os.path.exists(ACTIVE_STREAMS_FILE):
        try:
            with open(ACTIVE_STREAMS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_active_streams(active_streams):
    """Save active streams tracking"""
    try:
        with open(ACTIVE_STREAMS_FILE, "w") as f:
            json.dump(active_streams, f, indent=2)
    except Exception as e:
        st.error(f"Error saving active streams: {e}")

def load_templates():
    """Load stream templates"""
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, "r") as f:
                return json.load(f)
        except:
            return get_default_templates()
    return get_default_templates()

def save_templates(templates):
    """Save stream templates"""
    try:
        with open(TEMPLATES_FILE, "w") as f:
            json.dump(templates, f, indent=2)
    except Exception as e:
        st.error(f"Error saving templates: {e}")

def get_default_templates():
    """Get default stream templates"""
    return {
        "Gaming Stream": {
            "quality": "1080p",
            "is_shorts": False,
            "description": "Gaming live stream with high quality settings",
            "privacy_status": "public",
            "auto_create_youtube": True
        },
        "Music Stream": {
            "quality": "720p",
            "is_shorts": False,
            "description": "Music live stream with optimized audio settings",
            "privacy_status": "public",
            "auto_create_youtube": True
        },
        "YouTube Shorts": {
            "quality": "720p",
            "is_shorts": True,
            "description": "Vertical video stream for YouTube Shorts",
            "privacy_status": "public",
            "auto_create_youtube": True
        },
        "Low Bandwidth": {
            "quality": "480p",
            "is_shorts": False,
            "description": "Low bandwidth stream for slower connections",
            "privacy_status": "unlisted",
            "auto_create_youtube": False
        },
        "High Quality": {
            "quality": "1080p",
            "is_shorts": False,
            "description": "Maximum quality stream for premium content",
            "privacy_status": "public",
            "auto_create_youtube": True
        }
    }

def load_analytics():
    """Load analytics data"""
    if os.path.exists(ANALYTICS_FILE):
        try:
            with open(ANALYTICS_FILE, "r") as f:
                return json.load(f)
        except:
            return {"total_streams": 0, "successful_streams": 0, "failed_streams": 0, "total_duration": 0}
    return {"total_streams": 0, "successful_streams": 0, "failed_streams": 0, "total_duration": 0}

def save_analytics(analytics):
    """Save analytics data"""
    try:
        with open(ANALYTICS_FILE, "w") as f:
            json.dump(analytics, f, indent=2)
    except Exception as e:
        st.error(f"Error saving analytics: {e}")

def check_ffmpeg():
    """Check if ffmpeg is installed and available"""
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        st.error("FFmpeg is not installed or not in PATH. Please install FFmpeg to use this application.")
        st.markdown("""
        ### How to install FFmpeg:
        
        - **Ubuntu/Debian**: `sudo apt-get install ffmpeg`
        - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
        - **macOS**: `brew install ffmpeg`
        """)
        return False
    return True

def is_process_running(pid):
    """Check if a process with given PID is still running"""
    try:
        if psutil.pid_exists(pid):
            process = psutil.Process(pid)
            if 'ffmpeg' in process.name().lower():
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False

def reconnect_to_existing_streams():
    """Reconnect to streams that are still running after page refresh"""
    active_streams = load_active_streams()
    
    pid_files = [f for f in os.listdir('.') if f.startswith('stream_') and f.endswith('.pid')]
    
    for pid_file in pid_files:
        try:
            row_id = int(pid_file.split('_')[1].split('.')[0])
            
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            
            if is_process_running(pid):
                if row_id < len(st.session_state.streams):
                    st.session_state.streams.loc[row_id, 'Status'] = 'Sedang Live'
                    active_streams[str(row_id)] = {
                        'pid': pid,
                        'started_at': datetime.datetime.now().isoformat()
                    }
            else:
                cleanup_stream_files(row_id)
                if str(row_id) in active_streams:
                    del active_streams[str(row_id)]
                
        except (ValueError, FileNotFoundError, IOError):
            try:
                os.remove(pid_file)
            except:
                pass
    
    save_active_streams(active_streams)

def cleanup_stream_files(row_id):
    """Clean up all files related to a stream"""
    files_to_remove = [
        f"stream_{row_id}.pid",
        f"stream_{row_id}.status"
    ]
    
    for file_name in files_to_remove:
        try:
            if os.path.exists(file_name):
                os.remove(file_name)
        except:
            pass

def get_quality_settings(quality, is_shorts=False):
    """Get optimized encoding settings based on quality"""
    settings = {
        "720p": {
            "video_bitrate": "2500k",
            "audio_bitrate": "128k",
            "maxrate": "2750k",
            "bufsize": "5500k",
            "scale": "1280:720" if not is_shorts else "720:1280",
            "fps": "30"
        },
        "1080p": {
            "video_bitrate": "4500k",
            "audio_bitrate": "192k",
            "maxrate": "4950k",
            "bufsize": "9900k",
            "scale": "1920:1080" if not is_shorts else "1080:1920",
            "fps": "30"
        },
        "480p": {
            "video_bitrate": "1000k",
            "audio_bitrate": "96k",
            "maxrate": "1100k",
            "bufsize": "2200k",
            "scale": "854:480" if not is_shorts else "480:854",
            "fps": "30"
        }
    }
    return settings.get(quality, settings["720p"])

def run_ffmpeg(video_path, stream_key, is_shorts, row_id, quality="720p"):
    """Stream a video file to RTMP server using ffmpeg with optimized settings"""
    output_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
    
    log_file = f"stream_{row_id}.log"
    with open(log_file, "w") as f:
        f.write(f"Starting optimized stream for {video_path} at {datetime.datetime.now()}\n")
        f.write(f"Quality: {quality}, Shorts: {is_shorts}\n")
    
    settings = get_quality_settings(quality, is_shorts)
    
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "info",
        "-re",
        "-stream_loop", "-1",
        "-i", video_path,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-profile:v", "high",
        "-level", "4.1",
        "-pix_fmt", "yuv420p",
        "-b:v", settings["video_bitrate"],
        "-maxrate", settings["maxrate"],
        "-bufsize", settings["bufsize"],
        "-minrate", str(int(settings["video_bitrate"].replace('k', '')) // 2) + "k",
        "-g", "60",
        "-keyint_min", "30",
        "-sc_threshold", "0",
        "-r", settings["fps"],
        "-c:a", "aac",
        "-b:a", settings["audio_bitrate"],
        "-ar", "44100",
        "-ac", "2",
        "-vf", f"scale={settings['scale']}:force_original_aspect_ratio=decrease,pad={settings['scale']}:(ow-iw)/2:(oh-ih)/2,fps={settings['fps']}",
        "-f", "flv",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        output_url
    ]
    
    with open(log_file, "a") as f:
        f.write(f"Running: {' '.join(cmd)}\n")
    
    try:
        if os.name == 'nt':
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                bufsize=1,
                preexec_fn=os.setsid
            )
        
        with open(f"stream_{row_id}.pid", "w") as f:
            f.write(str(process.pid))
        
        with open(f"stream_{row_id}.status", "w") as f:
            f.write("streaming")
        
        active_streams = load_active_streams()
        active_streams[str(row_id)] = {
            'pid': process.pid,
            'started_at': datetime.datetime.now().isoformat()
        }
        save_active_streams(active_streams)
        
        def log_output():
            try:
                for line in process.stdout:
                    with open(log_file, "a") as f:
                        f.write(line)
                    if "Connection refused" in line or "Server returned 4" in line:
                        with open(f"stream_{row_id}.status", "w") as f:
                            f.write("error: YouTube connection failed")
            except:
                pass
        
        log_thread = threading.Thread(target=log_output, daemon=True)
        log_thread.start()
        
        process.wait()
        
        with open(f"stream_{row_id}.status", "w") as f:
            f.write("completed")
        
        with open(log_file, "a") as f:
            f.write("Streaming completed.\n")
        
        active_streams = load_active_streams()
        if str(row_id) in active_streams:
            del active_streams[str(row_id)]
        save_active_streams(active_streams)
        
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        
        with open(log_file, "a") as f:
            f.write(f"{error_msg}\n")
        
        with open(f"stream_{row_id}.status", "w") as f:
            f.write(f"error: {str(e)}")
        
        active_streams = load_active_streams()
        if str(row_id) in active_streams:
            del active_streams[str(row_id)]
        save_active_streams(active_streams)
    
    finally:
        with open(log_file, "a") as f:
            f.write("Streaming finished or stopped.\n")
        
        cleanup_stream_files(row_id)

def start_stream(video_path, stream_key, is_shorts, row_id, quality="720p", broadcast_id=None):
    """Start a stream in a separate process"""
    try:
        st.session_state.streams.loc[row_id, 'Status'] = 'Sedang Live'
        save_persistent_streams(st.session_state.streams)
        
        with open(f"stream_{row_id}.status", "w") as f:
            f.write("starting")
        
        # Start YouTube broadcast if broadcast_id is provided
        if broadcast_id:
            youtube = get_youtube_service()
            if youtube:
                update_youtube_broadcast_status(youtube, broadcast_id, 'testing')
                time.sleep(2)  # Wait a bit before going live
                update_youtube_broadcast_status(youtube, broadcast_id, 'live')
        
        thread = threading.Thread(
            target=run_ffmpeg,
            args=(video_path, stream_key, is_shorts, row_id, quality),
            daemon=False
        )
        thread.start()
        
        return True
    except Exception as e:
        st.error(f"Error starting stream: {e}")
        return False

def stop_stream(row_id):
    """Stop a running stream"""
    try:
        active_streams = load_active_streams()
        
        pid = None
        if str(row_id) in active_streams:
            pid = active_streams[str(row_id)]['pid']
        
        if not pid and os.path.exists(f"stream_{row_id}.pid"):
            with open(f"stream_{row_id}.pid", "r") as f:
                pid = int(f.read().strip())
        
        if pid and is_process_running(pid):
            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                                 capture_output=True, check=False)
                else:
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGTERM)
                        time.sleep(2)
                        if is_process_running(pid):
                            os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                
                # Stop YouTube broadcast if it exists
                if row_id < len(st.session_state.streams):
                    broadcast_id = st.session_state.streams.loc[row_id, 'YouTube Broadcast ID']
                    if pd.notna(broadcast_id) and broadcast_id:
                        youtube = get_youtube_service()
                        if youtube:
                            update_youtube_broadcast_status(youtube, broadcast_id, 'complete')
                
                st.session_state.streams.loc[row_id, 'Status'] = 'Dihentikan'
                save_persistent_streams(st.session_state.streams)
                
                with open(f"stream_{row_id}.status", "w") as f:
                    f.write("stopped")
                
                if str(row_id) in active_streams:
                    del active_streams[str(row_id)]
                save_active_streams(active_streams)
                
                cleanup_stream_files(row_id)
                
                return True
                
            except Exception as e:
                st.error(f"Error stopping stream: {str(e)}")
                return False
        else:
            st.session_state.streams.loc[row_id, 'Status'] = 'Dihentikan'
            save_persistent_streams(st.session_state.streams)
            cleanup_stream_files(row_id)
            
            if str(row_id) in active_streams:
                del active_streams[str(row_id)]
            save_active_streams(active_streams)
            
            return True
            
    except Exception as e:
        st.error(f"Error stopping stream: {str(e)}")
        return False

def check_stream_statuses():
    """Check status files for all streams and update accordingly"""
    active_streams = load_active_streams()
    
    for idx, row in st.session_state.streams.iterrows():
        status_file = f"stream_{idx}.status"
        
        if str(idx) in active_streams:
            pid = active_streams[str(idx)]['pid']
            
            if not is_process_running(pid):
                if row['Status'] == 'Sedang Live':
                    if os.path.exists(status_file):
                        with open(status_file, "r") as f:
                            status = f.read().strip()
                        
                        if status == "completed":
                            st.session_state.streams.loc[idx, 'Status'] = 'Selesai'
                        elif status.startswith("error:"):
                            st.session_state.streams.loc[idx, 'Status'] = status
                        else:
                            st.session_state.streams.loc[idx, 'Status'] = 'Terputus'
                        
                        save_persistent_streams(st.session_state.streams)
                        os.remove(status_file)
                    
                    del active_streams[str(idx)]
                    save_active_streams(active_streams)
                    cleanup_stream_files(idx)
        
        elif os.path.exists(status_file):
            with open(status_file, "r") as f:
                status = f.read().strip()
            
            if status == "completed" and row['Status'] == 'Sedang Live':
                st.session_state.streams.loc[idx, 'Status'] = 'Selesai'
                save_persistent_streams(st.session_state.streams)
                os.remove(status_file)
            
            elif status.startswith("error:") and row['Status'] == 'Sedang Live':
                st.session_state.streams.loc[idx, 'Status'] = status
                save_persistent_streams(st.session_state.streams)
                os.remove(status_file)

def check_scheduled_streams():
    """Check for streams that need to be started based on schedule"""
    current_time = datetime.datetime.now().strftime("%H:%M")
    
    for idx, row in st.session_state.streams.iterrows():
        if row['Status'] == 'Menunggu' and row['Jam Mulai'] == current_time:
            quality = row.get('Quality', '720p')
            broadcast_id = row.get('YouTube Broadcast ID', None)
            start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), idx, quality, broadcast_id)

def get_stream_logs(row_id, max_lines=100):
    """Get logs for a specific stream"""
    log_file = f"stream_{row_id}.log"
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            lines = f.readlines()
        return lines[-max_lines:] if len(lines) > max_lines else lines
    return []

def setup_youtube_oauth():
    """Setup YouTube OAuth authentication"""
    st.subheader("🔐 YouTube API Setup")
    
    config = load_youtube_config()
    
    with st.expander("📋 Setup Instructions", expanded=not config.get('client_id')):
        st.markdown("""
        ### How to get YouTube API credentials:
        
        1. **Go to Google Cloud Console**: [console.cloud.google.com](https://console.cloud.google.com)
        2. **Create a new project** or select existing one
        3. **Enable YouTube Data API v3**:
           - Go to "APIs & Services" > "Library"
           - Search for "YouTube Data API v3"
           - Click "Enable"
        4. **Create OAuth 2.0 credentials**:
           - Go to "APIs & Services" > "Credentials"
           - Click "Create Credentials" > "OAuth 2.0 Client ID"
           - Choose "Web application"
           - Add authorized redirect URI: `https://liveyt4.streamlit.app`
        5. **Download the JSON file** and copy Client ID & Client Secret below
        
        ### Required Scopes:
        - `https://www.googleapis.com/auth/youtube`
        - `https://www.googleapis.com/auth/youtube.force-ssl`
        """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        client_id = st.text_input(
            "Client ID", 
            value=config.get('client_id', ''),
            type="password",
            help="Your Google OAuth 2.0 Client ID"
        )
    
    with col2:
        client_secret = st.text_input(
            "Client Secret", 
            value=config.get('client_secret', ''),
            type="password",
            help="Your Google OAuth 2.0 Client Secret"
        )
    
    if st.button("💾 Save API Configuration"):
        if client_id and client_secret:
            config = {
                'client_id': client_id,
                'client_secret': client_secret
            }
            save_youtube_config(config)
            st.success("✅ API configuration saved!")
            st.rerun()
        else:
            st.error("❌ Please provide both Client ID and Client Secret")
    
    # Check if we have credentials
    credentials = load_youtube_credentials()
    
    if config.get('client_id') and config.get('client_secret'):
        if not credentials or not credentials.valid:
            st.warning("🔑 You need to authenticate with YouTube")
            
            if st.button("🚀 Authenticate with YouTube"):
                try:
                    # Create OAuth flow
                    flow = Flow.from_client_config(
                        {
                            "web": {
                                "client_id": config['client_id'],
                                "client_secret": config['client_secret'],
                                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                "token_uri": "https://oauth2.googleapis.com/token",
                                "redirect_uris": ["https://liveyt4.streamlit.app"]
                            }
                        },
                        scopes=YOUTUBE_SCOPES
                    )
                    flow.redirect_uri = "https://liveyt4.streamlit.app"
                    
                    # Get authorization URL
                    auth_url, _ = flow.authorization_url(prompt='consent')
                    
                    st.markdown(f"""
                    ### 🔗 Authorization Required
                    
                    1. **Click this link**: [Authorize YouTube Access]({auth_url})
                    2. **Sign in** to your YouTube account
                    3. **Grant permissions** to the application
                    4. **Copy the authorization code** from the URL
                    5. **Paste it below**
                    """)
                    
                    auth_code = st.text_input("📋 Authorization Code", help="Paste the code from the redirect URL")
                    
                    if st.button("✅ Complete Authentication") and auth_code:
                        try:
                            flow.fetch_token(code=auth_code)
                            save_youtube_credentials(flow.credentials)
                            st.success("🎉 Successfully authenticated with YouTube!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Authentication failed: {e}")
                
                except Exception as e:
                    st.error(f"❌ Error setting up authentication: {e}")
        else:
            st.success("✅ YouTube API is authenticated and ready!")
            
            # Show channel info
            youtube = get_youtube_service()
            if youtube:
                channel_info = get_youtube_channel_info(youtube)
                if channel_info:
                    st.info(f"📺 Connected to: **{channel_info['title']}** ({channel_info['subscriber_count']} subscribers)")
                
                if st.button("🔄 Refresh Authentication"):
                    try:
                        os.remove(YOUTUBE_CREDENTIALS_FILE)
                        st.success("Authentication cleared. Please re-authenticate.")
                        st.rerun()
                    except:
                        pass

def main():
    st.set_page_config(
        page_title="Live Streaming Scheduler - YouTube API Integrated",
        page_icon="📺",
        layout="wide"
    )
    
    st.title("🎥 Live Streaming Scheduler - YouTube API Integrated")
    
    if not check_ffmpeg():
        return
    
    if 'streams' not in st.session_state:
        st.session_state.streams = load_persistent_streams()
    
    reconnect_to_existing_streams()
    
    # Sidebar for ads and info
    show_ads = st.sidebar.checkbox("Tampilkan Iklan", value=False)
    if show_ads:
        st.sidebar.subheader("Iklan Sponsor")
        components.html(
            """
            <div style="background:#f0f2f6;padding:20px;border-radius:10px;text-align:center">
                <script type='text/javascript' 
                        src='//pl26562103.profitableratecpm.com/28/f9/95/28f9954a1d5bbf4924abe123c76a68d2.js'>
                </script>
                <p style="color:#888">Iklan akan muncul di sini</p>
            </div>
            """,
            height=300
        )
    
    check_stream_statuses()
    check_scheduled_streams()
    
    if st.sidebar.button("🔄 Refresh Status"):
        st.rerun()
    
    active_streams = load_active_streams()
    if active_streams:
        st.sidebar.success(f"🟢 {len(active_streams)} stream(s) berjalan")
    else:
        st.sidebar.info("⚫ Tidak ada stream aktif")
    
    # Create tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Stream Manager", "Add New Stream", "YouTube API", "Templates", "Analytics", "Logs"
    ])
    
    with tab1:
        st.subheader("Manage Streams")
        
        st.caption("✅ Status akan diperbarui otomatis. Streaming akan tetap berjalan meski halaman di-refresh.")
        st.caption("🎯 Optimized untuk YouTube Live dengan pengaturan encoding terbaik")
        st.caption("🤖 YouTube API terintegrasi untuk otomatis membuat live stream")
        
        if not st.session_state.streams.empty:
            header_cols = st.columns([2, 1, 1, 1, 2, 2, 2, 2])
            header_cols[0].write("**Video**")
            header_cols[1].write("**Duration**")
            header_cols[2].write("**Start Time**")
            header_cols[3].write("**Quality**")
            header_cols[4].write("**Streaming Key**")
            header_cols[5].write("**Status**")
            header_cols[6].write("**YouTube**")
            header_cols[7].write("**Action**")
            
            for i, row in st.session_state.streams.iterrows():
                cols = st.columns([2, 1, 1, 1, 2, 2, 2, 2])
                cols[0].write(os.path.basename(row['Video']))
                cols[1].write(row['Durasi'])
                cols[2].write(row['Jam Mulai'])
                cols[3].write(row.get('Quality', '720p'))
                
                masked_key = row['Streaming Key'][:4] + "****" if len(row['Streaming Key']) > 4 else "****"
                cols[4].write(masked_key)
                
                status = row['Status']
                if status == 'Sedang Live':
                    cols[5].markdown(f"🟢 **{status}**")
                elif status == 'Menunggu':
                    cols[5].markdown(f"🟡 **{status}**")
                elif status == 'Selesai':
                    cols[5].markdown(f"🔵 **{status}**")
                elif status == 'Dihentikan':
                    cols[5].markdown(f"🟠 **{status}**")
                elif status.startswith('error:'):
                    cols[5].markdown(f"🔴 **Error**")
                else:
                    cols[5].write(status)
                
                # YouTube info
                if pd.notna(row.get('YouTube Watch URL')) and row.get('YouTube Watch URL'):
                    cols[6].markdown(f"[📺 Watch]({row['YouTube Watch URL']})")
                elif row.get('Auto Created'):
                    cols[6].write("🤖 Auto")
                else:
                    cols[6].write("➖")
                
                # Action buttons
                if row['Status'] == 'Menunggu':
                    if cols[7].button("▶️ Start", key=f"start_{i}"):
                        quality = row.get('Quality', '720p')
                        broadcast_id = row.get('YouTube Broadcast ID')
                        if start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), i, quality, broadcast_id):
                            st.rerun()
                
                elif row['Status'] == 'Sedang Live':
                    if cols[7].button("⏹️ Stop", key=f"stop_{i}"):
                        if stop_stream(i):
                            st.rerun()
                
                elif row['Status'] in ['Selesai', 'Dihentikan', 'Terputus'] or row['Status'].startswith('error:'):
                    if cols[7].button("🗑️ Remove", key=f"remove_{i}"):
                        st.session_state.streams = st.session_state.streams.drop(i).reset_index(drop=True)
                        save_persistent_streams(st.session_state.streams)
                        log_file = f"stream_{i}.log"
                        if os.path.exists(log_file):
                            os.remove(log_file)
                        st.rerun()
        else:
            st.info("No streams added yet. Use the 'Add New Stream' tab to add a stream.")
    
    with tab2:
        st.subheader("Add New Stream")
        
        video_files = [f for f in os.listdir('.') if f.endswith(('.mp4', '.flv', '.avi', '.mov', '.mkv'))]
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Video Selection:**")
            selected_video = st.selectbox("Pilih video", [""] + video_files) if video_files else None
            
            uploaded_file = st.file_uploader("Atau upload video baru", type=['mp4', 'flv', 'avi', 'mov', 'mkv'])
            
            if uploaded_file:
                with open(uploaded_file.name, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                st.success("Video berhasil diupload!")
                video_path = uploaded_file.name
            elif selected_video:
                video_path = selected_video
            else:
                video_path = None
            
            # Template selection
            templates = load_templates()
            template_names = ["Custom"] + list(templates.keys())
            selected_template = st.selectbox("📋 Use Template", template_names)
        
        with col2:
            st.write("**Stream Configuration:**")
            
            # Auto-create YouTube stream option
            auto_create_youtube = st.checkbox("🤖 Auto-create YouTube Live Stream", value=True)
            
            if auto_create_youtube:
                stream_title = st.text_input("📺 Stream Title", value="Live Stream")
                stream_description = st.text_area("📝 Stream Description", value="Live streaming session")
                privacy_status = st.selectbox("🔒 Privacy", ["public", "unlisted", "private"], index=1)
                stream_key = ""  # Will be auto-generated
            else:
                stream_key = st.text_input("🔑 Stream Key", type="password")
                stream_title = ""
                stream_description = ""
                privacy_status = "unlisted"
            
            # Apply template if selected
            if selected_template != "Custom" and selected_template in templates:
                template = templates[selected_template]
                quality = st.selectbox("🎥 Quality", ["480p", "720p", "1080p"], 
                                     index=["480p", "720p", "1080p"].index(template["quality"]))
                is_shorts = st.checkbox("📱 Mode Shorts (Vertical)", value=template["is_shorts"])
                if auto_create_youtube and not stream_description:
                    stream_description = template["description"]
                    privacy_status = template["privacy_status"]
            else:
                quality = st.selectbox("🎥 Quality", ["480p", "720p", "1080p"], index=1)
                is_shorts = st.checkbox("📱 Mode Shorts (Vertical)")
            
            # Scheduling
            now = datetime.datetime.now()
            start_date = st.date_input("📅 Start Date", value=now.date())
            start_time = st.time_input("⏰ Start Time", value=now.time())
            start_datetime = datetime.datetime.combine(start_date, start_time)
            start_time_str = start_time.strftime("%H:%M")
            
            duration = st.text_input("⏱️ Duration (HH:MM:SS)", value="01:00:00")
        
        if st.button("➕ Add Stream"):
            if video_path and (stream_key or auto_create_youtube):
                youtube_info = {}
                
                if auto_create_youtube:
                    if not stream_title:
                        st.error("❌ Please provide a stream title for auto-creation")
                        return
                    
                    with st.spinner("🤖 Creating YouTube Live Stream..."):
                        youtube_info = auto_create_youtube_stream(
                            stream_title, stream_description, start_datetime, privacy_status
                        )
                    
                    if youtube_info:
                        stream_key = youtube_info['stream_key']
                        st.success(f"✅ YouTube Live Stream created! Watch URL: {youtube_info['watch_url']}")
                    else:
                        st.error("❌ Failed to create YouTube Live Stream. Please check your API setup.")
                        return
                
                video_filename = os.path.basename(video_path)
                
                new_stream = pd.DataFrame({
                    'Video': [video_path],
                    'Durasi': [duration],
                    'Jam Mulai': [start_time_str],
                    'Streaming Key': [stream_key],
                    'Status': ['Menunggu'],
                    'Is Shorts': [is_shorts],
                    'Quality': [quality],
                    'YouTube Broadcast ID': [youtube_info.get('broadcast_id', '')],
                    'YouTube Watch URL': [youtube_info.get('watch_url', '')],
                    'Auto Created': [auto_create_youtube],
                    'Stream Title': [stream_title],
                    'Stream Description': [stream_description]
                })
                
                st.session_state.streams = pd.concat([st.session_state.streams, new_stream], ignore_index=True)
                save_persistent_streams(st.session_state.streams)
                st.success(f"✅ Added stream for {video_filename} with {quality} quality")
                st.rerun()
            else:
                if not video_path:
                    st.error("❌ Please provide a video path")
                if not stream_key and not auto_create_youtube:
                    st.error("❌ Please provide a streaming key or enable auto-creation")
    
    with tab3:
        setup_youtube_oauth()
        
        # Show recent broadcasts
        youtube = get_youtube_service()
        if youtube:
            st.subheader("📺 Recent YouTube Live Broadcasts")
            
            broadcasts = get_youtube_live_broadcasts(youtube)
            if broadcasts:
                for broadcast in broadcasts[:5]:  # Show last 5
                    with st.expander(f"🎥 {broadcast['title']} - {broadcast['status']}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"**Status:** {broadcast['status']}")
                            st.write(f"**Privacy:** {broadcast['privacy_status']}")
                            if broadcast['scheduled_start_time']:
                                st.write(f"**Scheduled:** {broadcast['scheduled_start_time']}")
                        with col2:
                            st.markdown(f"[📺 Watch Stream]({broadcast['watch_url']})")
                            if broadcast['description']:
                                st.write(f"**Description:** {broadcast['description'][:100]}...")
            else:
                st.info("No recent broadcasts found.")
    
    with tab4:
        st.subheader("📋 Stream Templates")
        
        templates = load_templates()
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.write("**Available Templates:**")
            for name, template in templates.items():
                with st.expander(f"📄 {name}"):
                    st.write(f"**Quality:** {template['quality']}")
                    st.write(f"**Shorts Mode:** {'Yes' if template['is_shorts'] else 'No'}")
                    st.write(f"**Auto YouTube:** {'Yes' if template.get('auto_create_youtube', False) else 'No'}")
                    st.write(f"**Description:** {template['description']}")
                    
                    if st.button(f"🗑️ Delete {name}", key=f"del_{name}"):
                        if name not in get_default_templates():
                            del templates[name]
                            save_templates(templates)
                            st.success(f"Template '{name}' deleted!")
                            st.rerun()
                        else:
                            st.error("Cannot delete default template!")
        
        with col2:
            st.write("**Create New Template:**")
            
            template_name = st.text_input("Template Name")
            template_quality = st.selectbox("Quality", ["480p", "720p", "1080p"])
            template_shorts = st.checkbox("Shorts Mode")
            template_auto_youtube = st.checkbox("Auto Create YouTube")
            template_description = st.text_area("Description")
            template_privacy = st.selectbox("Privacy", ["public", "unlisted", "private"])
            
            if st.button("💾 Save Template"):
                if template_name and template_name not in templates:
                    templates[template_name] = {
                        "quality": template_quality,
                        "is_shorts": template_shorts,
                        "auto_create_youtube": template_auto_youtube,
                        "description": template_description,
                        "privacy_status": template_privacy
                    }
                    save_templates(templates)
                    st.success(f"Template '{template_name}' saved!")
                    st.rerun()
                elif template_name in templates:
                    st.error("Template name already exists!")
                else:
                    st.error("Please provide a template name!")
    
    with tab5:
        st.subheader("📊 Analytics Dashboard")
        
        analytics = load_analytics()
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Streams", analytics.get('total_streams', 0))
        
        with col2:
            st.metric("Successful", analytics.get('successful_streams', 0))
        
        with col3:
            st.metric("Failed", analytics.get('failed_streams', 0))
        
        with col4:
            success_rate = 0
            if analytics.get('total_streams', 0) > 0:
                success_rate = (analytics.get('successful_streams', 0) / analytics.get('total_streams', 0)) * 100
            st.metric("Success Rate", f"{success_rate:.1f}%")
        
        # Quality distribution
        if not st.session_state.streams.empty:
            st.subheader("📈 Quality Distribution")
            quality_counts = st.session_state.streams['Quality'].value_counts()
            st.bar_chart(quality_counts)
            
            st.subheader("📊 Status Distribution")
            status_counts = st.session_state.streams['Status'].value_counts()
            st.bar_chart(status_counts)
        
        # System resources
        st.subheader("💻 System Resources")
        try:
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('.')
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("CPU Usage", f"{cpu_percent}%")
            with col2:
                st.metric("Memory Usage", f"{memory.percent}%")
            with col3:
                st.metric("Disk Usage", f"{disk.percent}%")
        except:
            st.info("System resource monitoring not available")
    
    with tab6:
        st.subheader("📋 Stream Logs")
        
        log_files = [f for f in os.listdir('.') if f.startswith('stream_') and f.endswith('.log')]
        stream_ids = [int(f.split('_')[1].split('.')[0]) for f in log_files]
        
        if stream_ids:
            stream_options = {}
            for idx in stream_ids:
                if idx in st.session_state.streams.index:
                    video_name = os.path.basename(st.session_state.streams.loc[idx, 'Video'])
                    stream_options[f"{video_name} (ID: {idx})"] = idx
            
            if stream_options:
                selected_stream = st.selectbox("Select stream to view logs", options=list(stream_options.keys()))
                selected_id = stream_options[selected_stream]
                
                logs = get_stream_logs(selected_id)
                log_container = st.container()
                with log_container:
                    st.code("".join(logs))
                
                auto_refresh = st.checkbox("Auto-refresh logs", value=False)
                if auto_refresh:
                    time.sleep(3)
                    st.rerun()
            else:
                st.info("No logs available. Start a stream to see logs.")
        else:
            st.info("No logs available. Start a stream to see logs.")
    
    # Instructions
    with st.sidebar.expander("📖 How to use"):
        st.markdown("""
        ### 🚀 New Features:
        
        **🤖 YouTube API Integration:**
        - Auto-create YouTube Live streams
        - Automatic stream key generation
        - Broadcast management
        - Channel analytics
        
        **📋 Templates:**
        - Pre-built streaming configurations
        - Custom template creation
        - Quick setup for different scenarios
        
        **📊 Analytics:**
        - Stream success tracking
        - System resource monitoring
        - Quality distribution analysis
        
        ### 📋 Instructions:
        
        1. **Setup YouTube API** (Tab 3):
           - Get Google Cloud credentials
           - Authenticate with YouTube
        
        2. **Add Stream** (Tab 2):
           - Select video file
           - Choose template or custom settings
           - Enable auto-creation for YouTube
           - Set schedule and quality
        
        3. **Manage Streams** (Tab 1):
           - Start/stop streams
           - Monitor status
           - View YouTube links
        
        ### 💡 Tips:
        
        - Use templates for consistent settings
        - Enable auto-creation for easier setup
        - Monitor analytics for optimization
        - Check logs for troubleshooting
        """)
    
    time.sleep(1)

if __name__ == '__main__':
    main()
