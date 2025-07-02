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
import urllib.parse

# Install required packages if not already installed
required_packages = [
    "streamlit", "pandas", "psutil", 
    "google-auth", "google-auth-oauthlib", 
    "google-auth-httplib2", "google-api-python-client", "requests"
]

for package in required_packages:
    try:
        __import__(package.replace("-", "_"))
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

import streamlit as st
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import requests

# Persistent storage files
STREAMS_FILE = "streams_data.json"
ACTIVE_STREAMS_FILE = "active_streams.json"
YOUTUBE_CREDENTIALS_FILE = "youtube_credentials.json"

def load_persistent_streams():
    """Load streams from persistent storage"""
    if os.path.exists(STREAMS_FILE):
        try:
            with open(STREAMS_FILE, "r") as f:
                data = json.load(f)
                return pd.DataFrame(data)
        except:
            return pd.DataFrame(columns=[
                'Video', 'Durasi', 'Jam Mulai', 'Streaming Key', 'Status', 'Is Shorts', 'Quality', 'Broadcast ID', 'Watch URL'
            ])
    return pd.DataFrame(columns=[
        'Video', 'Durasi', 'Jam Mulai', 'Streaming Key', 'Status', 'Is Shorts', 'Quality', 'Broadcast ID', 'Watch URL'
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

def save_youtube_credentials(credentials):
    """Save YouTube credentials to file"""
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
        return True
    except Exception as e:
        st.error(f"Error saving credentials: {e}")
        return False

def load_youtube_credentials():
    """Load YouTube credentials from file"""
    if os.path.exists(YOUTUBE_CREDENTIALS_FILE):
        try:
            with open(YOUTUBE_CREDENTIALS_FILE, "r") as f:
                creds_data = json.load(f)
            
            credentials = Credentials(
                token=creds_data.get('token'),
                refresh_token=creds_data.get('refresh_token'),
                token_uri=creds_data.get('token_uri'),
                client_id=creds_data.get('client_id'),
                client_secret=creds_data.get('client_secret'),
                scopes=creds_data.get('scopes')
            )
            
            # Refresh if expired
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                save_youtube_credentials(credentials)
            
            return credentials
        except Exception as e:
            st.error(f"Error loading credentials: {e}")
            return None
    return None

def handle_oauth_callback():
    """Handle OAuth callback from URL parameters"""
    # Check if we have authorization code in URL parameters
    query_params = st.experimental_get_query_params()
    
    if 'code' in query_params and 'client_id' in st.session_state and 'client_secret' in st.session_state:
        try:
            auth_code = query_params['code'][0]
            
            # Exchange authorization code for tokens
            token_url = "https://oauth2.googleapis.com/token"
            
            data = {
                'client_id': st.session_state.client_id,
                'client_secret': st.session_state.client_secret,
                'code': auth_code,
                'grant_type': 'authorization_code',
                'redirect_uri': 'https://liveyt4.streamlit.app'  # Your actual Streamlit app URL
            }
            
            response = requests.post(token_url, data=data)
            
            if response.status_code == 200:
                token_data = response.json()
                
                # Create credentials object
                credentials = Credentials(
                    token=token_data['access_token'],
                    refresh_token=token_data.get('refresh_token'),
                    token_uri=token_url,
                    client_id=st.session_state.client_id,
                    client_secret=st.session_state.client_secret,
                    scopes=['https://www.googleapis.com/auth/youtube.force-ssl']
                )
                
                # Save credentials
                if save_youtube_credentials(credentials):
                    st.session_state.youtube_authenticated = True
                    st.session_state.youtube_credentials = credentials
                    st.success("✅ YouTube authentication successful!")
                    
                    # Clear URL parameters
                    st.experimental_set_query_params()
                    st.rerun()
                else:
                    st.error("Failed to save credentials")
            else:
                st.error(f"Token exchange failed: {response.text}")
                
        except Exception as e:
            st.error(f"Error handling OAuth callback: {e}")

def authenticate_youtube_manual():
    """Manual YouTube authentication with proper redirect URI"""
    if 'client_id' not in st.session_state or 'client_secret' not in st.session_state:
        st.error("Please enter Client ID and Client Secret first")
        return
    
    try:
        # Create OAuth URL manually
        client_id = st.session_state.client_id
        redirect_uri = "https://liveyt4.streamlit.app"  # Your actual Streamlit app URL
        scope = "https://www.googleapis.com/auth/youtube.force-ssl"
        
        auth_url = (
            f"https://accounts.google.com/o/oauth2/auth?"
            f"client_id={client_id}&"
            f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
            f"scope={urllib.parse.quote(scope)}&"
            f"response_type=code&"
            f"access_type=offline&"
            f"prompt=consent"
        )
        
        st.markdown(f"""
        ### 🔐 YouTube Authentication
        
        **Step 1:** Click the link below to authorize the application:
        
        **[🔗 Authorize YouTube Access]({auth_url})**
        
        **Step 2:** After authorization, you will be redirected back to this page automatically.
        
        **Step 3:** The page will refresh and show authentication success.
        
        ---
        
        **Note:** Make sure you're logged into the correct Google account that owns the YouTube channel you want to stream to.
        """)
        
    except Exception as e:
        st.error(f"Error creating authentication URL: {e}")

def get_youtube_service():
    """Get authenticated YouTube service"""
    credentials = load_youtube_credentials()
    if credentials:
        try:
            service = build('youtube', 'v3', credentials=credentials)
            return service
        except Exception as e:
            st.error(f"Error creating YouTube service: {e}")
            return None
    return None

def create_youtube_broadcast(title, description, start_time, privacy_status='unlisted'):
    """Create a YouTube Live broadcast"""
    service = get_youtube_service()
    if not service:
        return None, None
    
    try:
        # Create broadcast
        broadcast_response = service.liveBroadcasts().insert(
            part='snippet,status',
            body={
                'snippet': {
                    'title': title,
                    'description': description,
                    'scheduledStartTime': start_time.isoformat() + 'Z'
                },
                'status': {
                    'privacyStatus': privacy_status,
                    'selfDeclaredMadeForKids': False
                }
            }
        ).execute()
        
        broadcast_id = broadcast_response['id']
        
        # Create stream
        stream_response = service.liveStreams().insert(
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
        
        # Bind broadcast to stream
        service.liveBroadcasts().bind(
            part='id',
            id=broadcast_id,
            streamId=stream_id
        ).execute()
        
        watch_url = f"https://www.youtube.com/watch?v={broadcast_id}"
        
        return {
            'broadcast_id': broadcast_id,
            'stream_id': stream_id,
            'stream_key': stream_key,
            'watch_url': watch_url,
            'title': title
        }, None
        
    except Exception as e:
        return None, str(e)

def create_quick_broadcast(video_name):
    """Create a quick broadcast for immediate streaming"""
    if not st.session_state.youtube_authenticated:
        return None, "YouTube API not connected"
    
    try:
        # Generate title based on video name and current time
        base_name = os.path.splitext(video_name)[0]
        current_time = datetime.datetime.now()
        title = f"Live: {base_name} - {current_time.strftime('%d/%m/%Y %H:%M')}"
        description = f"Live streaming {base_name} via automated scheduler"
        
        # Set start time to now
        start_time = current_time + datetime.timedelta(minutes=1)  # Start in 1 minute
        
        broadcast_info, error = create_youtube_broadcast(title, description, start_time, 'unlisted')
        
        if broadcast_info:
            return broadcast_info, None
        else:
            return None, error
            
    except Exception as e:
        return None, str(e)

def start_youtube_broadcast(broadcast_id):
    """Start a YouTube Live broadcast"""
    service = get_youtube_service()
    if not service:
        return False, "YouTube service not available"
    
    try:
        service.liveBroadcasts().transition(
            part='id',
            id=broadcast_id,
            broadcastStatus='live'
        ).execute()
        return True, "Broadcast started successfully"
    except Exception as e:
        return False, str(e)

def stop_youtube_broadcast(broadcast_id):
    """Stop a YouTube Live broadcast"""
    service = get_youtube_service()
    if not service:
        return False, "YouTube service not available"
    
    try:
        service.liveBroadcasts().transition(
            part='id',
            id=broadcast_id,
            broadcastStatus='complete'
        ).execute()
        return True, "Broadcast stopped successfully"
    except Exception as e:
        return False, str(e)

def get_channel_info():
    """Get YouTube channel information"""
    service = get_youtube_service()
    if not service:
        return None
    
    try:
        response = service.channels().list(
            part='snippet,statistics',
            mine=True
        ).execute()
        
        if response['items']:
            channel = response['items'][0]
            return {
                'title': channel['snippet']['title'],
                'subscriber_count': channel['statistics'].get('subscriberCount', 'Hidden'),
                'view_count': channel['statistics'].get('viewCount', '0'),
                'video_count': channel['statistics'].get('videoCount', '0')
            }
    except Exception as e:
        st.error(f"Error getting channel info: {e}")
    
    return None

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
        if broadcast_id and st.session_state.youtube_authenticated:
            success, message = start_youtube_broadcast(broadcast_id)
            if not success:
                st.warning(f"Could not start YouTube broadcast: {message}")
        
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
        
        # Stop YouTube broadcast if broadcast_id exists
        if row_id < len(st.session_state.streams):
            broadcast_id = st.session_state.streams.loc[row_id, 'Broadcast ID']
            if pd.notna(broadcast_id) and broadcast_id and st.session_state.youtube_authenticated:
                success, message = stop_youtube_broadcast(broadcast_id)
                if not success:
                    st.warning(f"Could not stop YouTube broadcast: {message}")
        
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
            broadcast_id = row.get('Broadcast ID', None)
            start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), idx, quality, broadcast_id)

def get_stream_logs(row_id, max_lines=100):
    """Get logs for a specific stream"""
    log_file = f"stream_{row_id}.log"
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            lines = f.readlines()
        return lines[-max_lines:] if len(lines) > max_lines else lines
    return []

def main():
    st.set_page_config(
        page_title="Live Streaming Scheduler - YouTube Optimized",
        page_icon="📺",
        layout="wide"
    )
    
    st.title("🎥 Live Streaming Scheduler - YouTube Optimized")
    
    # Handle OAuth callback first
    handle_oauth_callback()
    
    # Check if ffmpeg is installed
    if not check_ffmpeg():
        return
    
    # Initialize session state with persistent data
    if 'streams' not in st.session_state:
        st.session_state.streams = load_persistent_streams()
    
    # Initialize YouTube authentication state
    if 'youtube_authenticated' not in st.session_state:
        credentials = load_youtube_credentials()
        st.session_state.youtube_authenticated = credentials is not None
        if credentials:
            st.session_state.youtube_credentials = credentials
    
    # Reconnect to existing streams after page refresh
    reconnect_to_existing_streams()
    
    # Sidebar for ads
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
    
    # Check status of running streams
    check_stream_statuses()
    
    # Check for scheduled streams
    check_scheduled_streams()
    
    # Auto-refresh controls
    if st.sidebar.button("🔄 Refresh Status"):
        st.rerun()
    
    # Show persistent stream info
    active_streams = load_active_streams()
    if active_streams:
        st.sidebar.success(f"🟢 {len(active_streams)} stream(s) berjalan")
    else:
        st.sidebar.info("⚫ Tidak ada stream aktif")
    
    # YouTube authentication status
    if st.session_state.youtube_authenticated:
        channel_info = get_channel_info()
        if channel_info:
            st.sidebar.success(f"✅ YouTube: {channel_info['title']}")
            st.sidebar.caption(f"👥 {channel_info['subscriber_count']} subscribers")
        else:
            st.sidebar.success("✅ YouTube: Connected")
    else:
        st.sidebar.warning("⚠️ YouTube: Not connected")
    
    # Create tabs for different sections
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Stream Manager", "Add New Stream", "YouTube API", "Logs", "Settings"])
    
    with tab1:
        st.subheader("Manage Streams")
        
        st.caption("✅ Status akan diperbarui otomatis. Streaming akan tetap berjalan meski halaman di-refresh.")
        st.caption("🎯 Optimized untuk YouTube Live dengan pengaturan encoding terbaik")
        
        if not st.session_state.streams.empty:
            header_cols = st.columns([2, 1, 1, 1, 2, 2, 2])
            header_cols[0].write("**Video**")
            header_cols[1].write("**Duration**")
            header_cols[2].write("**Start Time**")
            header_cols[3].write("**Quality**")
            header_cols[4].write("**Streaming Key**")
            header_cols[5].write("**Status**")
            header_cols[6].write("**Action**")
            
            for i, row in st.session_state.streams.iterrows():
                cols = st.columns([2, 1, 1, 1, 2, 2, 2])
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
                
                if row['Status'] == 'Menunggu':
                    if cols[6].button("▶️ Start", key=f"start_{i}"):
                        quality = row.get('Quality', '720p')
                        broadcast_id = row.get('Broadcast ID', None)
                        if start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), i, quality, broadcast_id):
                            st.rerun()
                
                elif row['Status'] == 'Sedang Live':
                    if cols[6].button("⏹️ Stop", key=f"stop_{i}"):
                        if stop_stream(i):
                            st.rerun()
                
                elif row['Status'] in ['Selesai', 'Dihentikan', 'Terputus'] or row['Status'].startswith('error:'):
                    if cols[6].button("🗑️ Remove", key=f"remove_{i}"):
                        st.session_state.streams = st.session_state.streams.drop(i).reset_index(drop=True)
                        save_persistent_streams(st.session_state.streams)
                        log_file = f"stream_{i}.log"
                        if os.path.exists(log_file):
                            os.remove(log_file)
                        st.rerun()
                
                # Show YouTube link if available
                watch_url = row.get('Watch URL', '')
                if watch_url:
                    cols[6].markdown(f"[🔗 YouTube]({watch_url})")
        else:
            st.info("No streams added yet. Use the 'Add New Stream' tab to add a stream.")
    
    with tab2:
        st.subheader("Add New Stream")
        
        video_files = [f for f in os.listdir('.') if f.endswith(('.mp4', '.flv', '.avi', '.mov', '.mkv'))]
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("Video yang tersedia:")
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
        
        with col2:
            # YouTube API Integration for Stream Key
            if st.session_state.youtube_authenticated:
                st.success("🎯 YouTube API Connected - Auto Stream Key Available!")
                
                use_auto_stream = st.checkbox("🚀 Auto-create YouTube Live Broadcast", value=True)
                
                if use_auto_stream:
                    st.info("✅ Stream key akan dibuat otomatis dari YouTube API")
                    stream_key = None  # Will be generated automatically
                else:
                    stream_key = st.text_input("Manual Stream Key", type="password")
            else:
                st.warning("⚠️ YouTube API not connected - Manual stream key required")
                use_auto_stream = False
                stream_key = st.text_input("Stream Key", type="password")
            
            now = datetime.datetime.now()
            start_time = st.time_input("Start Time", value=now)
            start_time_str = start_time.strftime("%H:%M")
            
            duration = st.text_input("Duration (HH:MM:SS)", value="01:00:00")
            
            quality = st.selectbox("Quality", ["480p", "720p", "1080p"], index=1)
            
            is_shorts = st.checkbox("Mode Shorts (Vertical)")
        
        if st.button("➕ Add Stream"):
            if video_path:
                video_filename = os.path.basename(video_path)
                
                # Auto-create YouTube broadcast if enabled
                if use_auto_stream and st.session_state.youtube_authenticated:
                    with st.spinner("🔄 Creating YouTube Live broadcast..."):
                        broadcast_info, error = create_quick_broadcast(video_filename)
                    
                    if broadcast_info:
                        st.success(f"✅ YouTube broadcast created: {broadcast_info['title']}")
                        stream_key = broadcast_info['stream_key']
                        broadcast_id = broadcast_info['broadcast_id']
                        watch_url = broadcast_info['watch_url']
                        
                        st.info(f"🔗 Watch URL: {watch_url}")
                    else:
                        st.error(f"❌ Failed to create broadcast: {error}")
                        return
                else:
                    if not stream_key:
                        st.error("Please provide a streaming key or enable auto-create")
                        return
                    broadcast_id = None
                    watch_url = ""
                
                new_stream = pd.DataFrame({
                    'Video': [video_path],
                    'Durasi': [duration],
                    'Jam Mulai': [start_time_str],
                    'Streaming Key': [stream_key],
                    'Status': ['Menunggu'],
                    'Is Shorts': [is_shorts],
                    'Quality': [quality],
                    'Broadcast ID': [broadcast_id if broadcast_id else ""],
                    'Watch URL': [watch_url if watch_url else ""]
                })
                
                st.session_state.streams = pd.concat([st.session_state.streams, new_stream], ignore_index=True)
                save_persistent_streams(st.session_state.streams)
                
                if use_auto_stream and st.session_state.youtube_authenticated:
                    st.success(f"✅ Added stream for {video_filename} with auto-generated YouTube broadcast!")
                else:
                    st.success(f"✅ Added stream for {video_filename} with {quality} quality")
                st.rerun()
            else:
                st.error("Please provide a video path")
    
    with tab3:
        st.subheader("🔴 YouTube API Integration")
        
        if not st.session_state.youtube_authenticated:
            st.warning("⚠️ YouTube API not connected. Connect to enable automatic broadcast creation.")
            
            with st.expander("🔧 Setup YouTube API", expanded=True):
                st.markdown("""
                ### 📋 Setup Instructions:
                
                1. **Go to [Google Cloud Console](https://console.cloud.google.com)**
                2. **Create a new project** or select existing one
                3. **Enable "YouTube Data API v3"**
                4. **Create OAuth 2.0 Client ID:**
                   - Application type: **Web application**
                   - Authorized redirect URIs: `https://liveyt4.streamlit.app`
                5. **Copy Client ID and Client Secret**
                """)
                
                col1, col2 = st.columns(2)
                with col1:
                    client_id = st.text_input("Client ID", key="client_id_input")
                with col2:
                    client_secret = st.text_input("Client Secret", type="password", key="client_secret_input")
                
                if st.button("💾 Save Credentials"):
                    if client_id and client_secret:
                        st.session_state.client_id = client_id
                        st.session_state.client_secret = client_secret
                        st.success("✅ Credentials saved! Now click 'Start Authentication' below.")
                    else:
                        st.error("Please enter both Client ID and Client Secret")
                
                if st.button("🔐 Start Authentication"):
                    authenticate_youtube_manual()
        
        else:
            st.success("✅ YouTube API Connected!")
            
            # Show channel info
            channel_info = get_channel_info()
            if channel_info:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Channel", channel_info['title'])
                col2.metric("Subscribers", channel_info['subscriber_count'])
                col3.metric("Total Views", channel_info['view_count'])
                col4.metric("Videos", channel_info['video_count'])
            
            st.subheader("🎬 Manual Broadcast Creation")
            st.caption("💡 Tip: Use 'Add New Stream' tab with auto-create enabled for easier workflow")
            
            with st.form("create_broadcast"):
                broadcast_title = st.text_input("Broadcast Title", value="Live Stream")
                broadcast_description = st.text_area("Description", value="Live streaming with automated scheduler")
                
                col1, col2 = st.columns(2)
                with col1:
                    broadcast_date = st.date_input("Date", value=datetime.date.today())
                with col2:
                    broadcast_time = st.time_input("Time", value=datetime.datetime.now().time())
                
                privacy_status = st.selectbox("Privacy", ["unlisted", "public", "private"], index=0)
                
                if st.form_submit_button("🔴 Create Broadcast"):
                    if broadcast_title:
                        # Combine date and time
                        start_datetime = datetime.datetime.combine(broadcast_date, broadcast_time)
                        
                        with st.spinner("Creating YouTube Live broadcast..."):
                            broadcast_info, error = create_youtube_broadcast(
                                broadcast_title, 
                                broadcast_description, 
                                start_datetime, 
                                privacy_status
                            )
                        
                        if broadcast_info:
                            st.success("✅ Broadcast created successfully!")
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                st.info(f"**Stream Key:** `{broadcast_info['stream_key']}`")
                                st.info(f"**Broadcast ID:** `{broadcast_info['broadcast_id']}`")
                            with col2:
                                st.info(f"**Watch URL:** {broadcast_info['watch_url']}")
                                st.markdown(f"[🔗 Open YouTube Live]({broadcast_info['watch_url']})")
                            
                            # Auto-add to streams
                            if st.button("➕ Add to Stream Manager"):
                                new_stream = pd.DataFrame({
                                    'Video': [''],  # Will be filled when video is selected
                                    'Durasi': ['01:00:00'],
                                    'Jam Mulai': [broadcast_time.strftime("%H:%M")],
                                    'Streaming Key': [broadcast_info['stream_key']],
                                    'Status': ['Menunggu'],
                                    'Is Shorts': [False],
                                    'Quality': ['720p'],
                                    'Broadcast ID': [broadcast_info['broadcast_id']],
                                    'Watch URL': [broadcast_info['watch_url']]
                                })
                                
                                st.session_state.streams = pd.concat([st.session_state.streams, new_stream], ignore_index=True)
                                save_persistent_streams(st.session_state.streams)
                                st.success("✅ Added to Stream Manager!")
                                st.rerun()
                        else:
                            st.error(f"❌ Error creating broadcast: {error}")
                    else:
                        st.error("Please enter a broadcast title")
            
            # Disconnect option
            if st.button("🔌 Disconnect YouTube API"):
                if os.path.exists(YOUTUBE_CREDENTIALS_FILE):
                    os.remove(YOUTUBE_CREDENTIALS_FILE)
                st.session_state.youtube_authenticated = False
                if 'youtube_credentials' in st.session_state:
                    del st.session_state.youtube_credentials
                st.success("✅ Disconnected from YouTube API")
                st.rerun()
    
    with tab4:
        st.subheader("Stream Logs")
        
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
    
    with tab5:
        st.subheader("⚙️ Streaming Settings & Tips")
        
        st.markdown("""
        ### 🎯 Optimizations Applied:
        
        ✅ **Bitrate Control**: Adaptive bitrate dengan buffer yang optimal  
        ✅ **Low Latency**: Tune zerolatency untuk streaming real-time  
        ✅ **Reconnection**: Auto-reconnect jika koneksi terputus  
        ✅ **GOP Settings**: Keyframe interval optimal untuk YouTube  
        ✅ **Audio Quality**: AAC encoding dengan sample rate 44.1kHz  
        ✅ **YouTube API**: Automatic broadcast creation dan management  
        ✅ **Auto Stream Key**: Otomatis generate stream key dari YouTube API  
        
        ### 📊 Quality Settings:
        
        - **480p**: 1000k video bitrate, 96k audio - untuk koneksi lambat
        - **720p**: 2500k video bitrate, 128k audio - recommended
        - **1080p**: 4500k video bitrate, 192k audio - untuk koneksi cepat
        
        ### 🚀 New Auto Features:
        
        **Auto YouTube Integration:**
        - ✅ Otomatis buat YouTube Live broadcast
        - ✅ Auto-generate stream key
        - ✅ Auto-start/stop broadcast
        - ✅ Direct YouTube watch links
        - ✅ No manual stream key needed!
        
        **Workflow Baru:**
        1. Connect YouTube API (sekali saja)
        2. Upload video
        3. Enable "Auto-create YouTube Live Broadcast"
        4. Klik "Add Stream" - Done! 🎉
        
        ### 🔧 Troubleshooting:
        
        **Jika masih ada buffering:**
        1. Gunakan quality 480p untuk koneksi internet lambat
        2. Pastikan upload speed minimal 3x dari bitrate yang dipilih
        3. Tutup aplikasi lain yang menggunakan internet
        4. Gunakan koneksi ethernet instead of WiFi
        
        **Untuk YouTube Shorts:**
        - Video akan otomatis di-scale ke aspect ratio vertikal
        - Gunakan video dengan resolusi 9:16 untuk hasil terbaik
        
        **YouTube API Features:**
        - Auto-create live broadcasts
        - Get stream keys automatically
        - Start/stop broadcasts remotely
        - Channel analytics integration
        - Direct YouTube links
        """)
        
        st.subheader("🌐 Network Test")
        if st.button("Test Upload Speed"):
            st.info("Untuk test upload speed yang akurat, gunakan speedtest.net")
            st.markdown("[🔗 Test Speed di Speedtest.net](https://speedtest.net)")
    
    # Instructions
    with st.sidebar.expander("📖 How to use"):
        st.markdown("""
        ### Instructions:
        
        1. **Setup YouTube API** (Recommended):
           - Go to YouTube API tab
           - Follow setup instructions
           - Connect your YouTube channel
        
        2. **Add a Stream**: 
           - Select or upload a video
           - ✅ **Enable "Auto-create YouTube Live Broadcast"**
           - Choose quality and settings
           - Set start time
           - **No manual stream key needed!**
        
        3. **Manage Streams**:
           - Start/stop streams manually
           - Auto-start at scheduled time
           - View logs for monitoring
           - **Streams continue running after page refresh!**
           - **Direct YouTube links available!**
        
        ### Requirements:
        
        - FFmpeg must be installed
        - Compatible video formats (MP4 recommended)
        - Stable internet (upload speed 3x bitrate)
        - YouTube API credentials (recommended)
        
        ### Quality Recommendations:
        
        - **480p**: Upload speed minimal 3 Mbps
        - **720p**: Upload speed minimal 8 Mbps  
        - **1080p**: Upload speed minimal 15 Mbps
        
        ### New Features:
        
        ✅ **Auto YouTube Integration**  
        ✅ **Auto-stream key generation**  
        ✅ **Auto-broadcast creation**  
        ✅ **Auto-start/stop broadcasts**  
        ✅ **Direct YouTube watch links**  
        ✅ **Enhanced error handling**  
        ✅ **Simplified workflow**  
        """)
    
    time.sleep(1)

if __name__ == '__main__':
    main()
