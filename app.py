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

# Install streamlit if not already installed
try:
    import streamlit as st
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "streamlit"])
    import streamlit as st

# Persistent storage file
STREAMS_FILE = "streams_data.json"
ACTIVE_STREAMS_FILE = "active_streams.json"

def load_persistent_streams():
    """Load streams from persistent storage"""
    if os.path.exists(STREAMS_FILE):
        try:
            with open(STREAMS_FILE, "r") as f:
                data = json.load(f)
                return pd.DataFrame(data)
        except:
            return pd.DataFrame(columns=[
                'Video', 'Durasi', 'Jam Mulai', 'Streaming Key', 'Status', 'Is Shorts'
            ])
    return pd.DataFrame(columns=[
        'Video', 'Durasi', 'Jam Mulai', 'Streaming Key', 'Status', 'Is Shorts'
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
        # Check if PID exists and is running
        if psutil.pid_exists(pid):
            process = psutil.Process(pid)
            # Check if it's actually an ffmpeg process
            if 'ffmpeg' in process.name().lower():
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False

def reconnect_to_existing_streams():
    """Reconnect to streams that are still running after page refresh"""
    active_streams = load_active_streams()
    
    # Get all existing PID files
    pid_files = [f for f in os.listdir('.') if f.startswith('stream_') and f.endswith('.pid')]
    
    for pid_file in pid_files:
        try:
            row_id = int(pid_file.split('_')[1].split('.')[0])
            
            # Check if PID file has valid running process
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            
            if is_process_running(pid):
                # Process is still running, update status
                if row_id < len(st.session_state.streams):
                    st.session_state.streams.loc[row_id, 'Status'] = 'Sedang Live'
                    active_streams[str(row_id)] = {
                        'pid': pid,
                        'started_at': datetime.datetime.now().isoformat()
                    }
            else:
                # Process is dead, clean up
                cleanup_stream_files(row_id)
                if str(row_id) in active_streams:
                    del active_streams[str(row_id)]
                
        except (ValueError, FileNotFoundError, IOError):
            # Invalid file, remove it
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

def run_ffmpeg(video_path, stream_key, is_shorts, row_id):
    """Stream a video file to RTMP server using ffmpeg"""
    output_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
    
    # Create log file
    log_file = f"stream_{row_id}.log"
    with open(log_file, "w") as f:
        f.write(f"Starting stream for {video_path} at {datetime.datetime.now()}\n")
    
    # Build command with appropriate settings
    cmd = [
        "ffmpeg", 
        "-re",                  # Read input at native frame rate
        "-stream_loop", "-1",   # Loop the video indefinitely
        "-i", video_path,       # Input file
        "-c:v", "libx264",      # Video codec
        "-preset", "veryfast",  # Encoding preset
        "-b:v", "2500k",        # Video bitrate
        "-maxrate", "2500k",    # Maximum bitrate
        "-bufsize", "5000k",    # Buffer size
        "-g", "60",             # GOP size
        "-keyint_min", "60",    # Minimum GOP size
        "-c:a", "aac",          # Audio codec
        "-b:a", "128k",         # Audio bitrate
        "-f", "flv"             # Output format
    ]
    
    # Add scale filter for shorts if needed
    if is_shorts:
        cmd += ["-vf", "scale=720:1280"]
    
    # Add output URL
    cmd.append(output_url)
    
    # Log the command
    with open(log_file, "a") as f:
        f.write(f"Running: {' '.join(cmd)}\n")
    
    try:
        # Start the process with CREATE_NEW_PROCESS_GROUP on Windows
        if os.name == 'nt':  # Windows
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:  # Unix/Linux/Mac
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                bufsize=1,
                preexec_fn=os.setsid  # Create new session
            )
        
        # Store process ID for later reference
        with open(f"stream_{row_id}.pid", "w") as f:
            f.write(str(process.pid))
        
        # Update status
        with open(f"stream_{row_id}.status", "w") as f:
            f.write("streaming")
        
        # Update active streams tracking
        active_streams = load_active_streams()
        active_streams[str(row_id)] = {
            'pid': process.pid,
            'started_at': datetime.datetime.now().isoformat()
        }
        save_active_streams(active_streams)
        
        # Read and log output in a separate thread to avoid blocking
        def log_output():
            try:
                for line in process.stdout:
                    with open(log_file, "a") as f:
                        f.write(line)
            except:
                pass
        
        log_thread = threading.Thread(target=log_output, daemon=True)
        log_thread.start()
        
        # Wait for process to complete
        process.wait()
        
        # Update status when done
        with open(f"stream_{row_id}.status", "w") as f:
            f.write("completed")
        
        with open(log_file, "a") as f:
            f.write("Streaming completed.\n")
        
        # Remove from active streams
        active_streams = load_active_streams()
        if str(row_id) in active_streams:
            del active_streams[str(row_id)]
        save_active_streams(active_streams)
        
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        
        # Write error to log file
        with open(log_file, "a") as f:
            f.write(f"{error_msg}\n")
        
        # Write error to status file
        with open(f"stream_{row_id}.status", "w") as f:
            f.write(f"error: {str(e)}")
        
        # Remove from active streams
        active_streams = load_active_streams()
        if str(row_id) in active_streams:
            del active_streams[str(row_id)]
        save_active_streams(active_streams)
    
    finally:
        with open(log_file, "a") as f:
            f.write("Streaming finished or stopped.\n")
        
        # Clean up PID file
        cleanup_stream_files(row_id)

def start_stream(video_path, stream_key, is_shorts, row_id):
    """Start a stream in a separate process (not thread)"""
    try:
        # Update status immediately
        st.session_state.streams.loc[row_id, 'Status'] = 'Sedang Live'
        save_persistent_streams(st.session_state.streams)
        
        # Write initial status file
        with open(f"stream_{row_id}.status", "w") as f:
            f.write("starting")
        
        # Start streaming in a separate thread (but make it non-daemon)
        thread = threading.Thread(
            target=run_ffmpeg,
            args=(video_path, stream_key, is_shorts, row_id),
            daemon=False  # Changed to False so it survives page refresh
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
        
        # First try to get PID from tracking
        pid = None
        if str(row_id) in active_streams:
            pid = active_streams[str(row_id)]['pid']
        
        # If not in tracking, try PID file
        if not pid and os.path.exists(f"stream_{row_id}.pid"):
            with open(f"stream_{row_id}.pid", "r") as f:
                pid = int(f.read().strip())
        
        if pid and is_process_running(pid):
            # Try to terminate the process gracefully
            try:
                if os.name == 'nt':  # Windows
                    # Use taskkill for Windows
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                                 capture_output=True, check=False)
                else:  # Unix/Linux/Mac
                    # Send SIGTERM first, then SIGKILL if needed
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGTERM)
                        time.sleep(2)  # Give it time to shut down gracefully
                        if is_process_running(pid):
                            os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # Process already terminated
                
                # Update status
                st.session_state.streams.loc[row_id, 'Status'] = 'Dihentikan'
                save_persistent_streams(st.session_state.streams)
                
                # Update status file
                with open(f"stream_{row_id}.status", "w") as f:
                    f.write("stopped")
                
                # Remove from active streams
                if str(row_id) in active_streams:
                    del active_streams[str(row_id)]
                save_active_streams(active_streams)
                
                # Clean up files
                cleanup_stream_files(row_id)
                
                return True
                
            except Exception as e:
                st.error(f"Error stopping stream: {str(e)}")
                return False
        else:
            # Process not found, just update status
            st.session_state.streams.loc[row_id, 'Status'] = 'Dihentikan'
            save_persistent_streams(st.session_state.streams)
            cleanup_stream_files(row_id)
            
            # Remove from active streams
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
        
        # Check if stream is supposed to be active
        if str(idx) in active_streams:
            pid = active_streams[str(idx)]['pid']
            
            # Check if process is still running
            if not is_process_running(pid):
                # Process died, update status
                if row['Status'] == 'Sedang Live':
                    # Check for completion status
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
                    
                    # Remove from active streams
                    del active_streams[str(idx)]
                    save_active_streams(active_streams)
                    cleanup_stream_files(idx)
        
        # Regular status file checking
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
            # Start the stream
            start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), idx)

def get_stream_logs(row_id, max_lines=100):
    """Get logs for a specific stream"""
    log_file = f"stream_{row_id}.log"
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            lines = f.readlines()
        return lines[-max_lines:] if len(lines) > max_lines else lines
    return []

def main():
    # Page configuration must be the first Streamlit command
    st.set_page_config(
        page_title="Live Streaming Scheduler",
        page_icon="📈",
        layout="wide"
    )
    
    st.title("Live Streaming Scheduler")
    
    # Check if ffmpeg is installed
    if not check_ffmpeg():
        return
    
    # Initialize session state with persistent data
    if 'streams' not in st.session_state:
        st.session_state.streams = load_persistent_streams()
    
    # Reconnect to existing streams after page refresh
    reconnect_to_existing_streams()
    
    # Bagian iklan
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
    
    # Auto-refresh every 10 seconds to check stream status
    if st.sidebar.button("🔄 Refresh Status"):
        st.rerun()
    
    # Show persistent stream info
    active_streams = load_active_streams()
    if active_streams:
        st.sidebar.success(f"🟢 {len(active_streams)} stream(s) berjalan")
    else:
        st.sidebar.info("⚫ Tidak ada stream aktif")
    
    # Create tabs for different sections
    tab1, tab2, tab3 = st.tabs(["Stream Manager", "Add New Stream", "Logs"])
    
    with tab1:
        st.subheader("Manage Streams")
        
        # Auto refresh indicator
        st.caption("Status akan diperbarui otomatis. Streaming akan tetap berjalan meski halaman di-refresh.")
        
        # Display the streams table with action buttons
        if not st.session_state.streams.empty:
            # Create a header row
            header_cols = st.columns([2, 1, 1, 2, 2, 2])
            header_cols[0].write("**Video**")
            header_cols[1].write("**Duration**")
            header_cols[2].write("**Start Time**")
            header_cols[3].write("**Streaming Key**")
            header_cols[4].write("**Status**")
            header_cols[5].write("**Action**")
            
            # Display each stream
            for i, row in st.session_state.streams.iterrows():
                cols = st.columns([2, 1, 1, 2, 2, 2])
                cols[0].write(os.path.basename(row['Video']))  # Just show filename
                cols[1].write(row['Durasi'])
                cols[2].write(row['Jam Mulai'])
                # Mask streaming key for security
                masked_key = row['Streaming Key'][:4] + "****" if len(row['Streaming Key']) > 4 else "****"
                cols[3].write(masked_key)
                
                # Status with color coding
                status = row['Status']
                if status == 'Sedang Live':
                    cols[4].markdown(f"🟢 **{status}**")
                elif status == 'Menunggu':
                    cols[4].markdown(f"🟡 **{status}**")
                elif status == 'Selesai':
                    cols[4].markdown(f"🔵 **{status}**")
                elif status == 'Dihentikan':
                    cols[4].markdown(f"🟠 **{status}**")
                elif status.startswith('error:'):
                    cols[4].markdown(f"🔴 **Error**")
                else:
                    cols[4].write(status)
                
                # Action buttons
                if row['Status'] == 'Menunggu':
                    if cols[5].button("▶️ Start", key=f"start_{i}"):
                        if start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), i):
                            st.rerun()
                
                elif row['Status'] == 'Sedang Live':
                    if cols[5].button("⏹️ Stop", key=f"stop_{i}"):
                        if stop_stream(i):
                            st.rerun()
                
                elif row['Status'] in ['Selesai', 'Dihentikan', 'Terputus'] or row['Status'].startswith('error:'):
                    if cols[5].button("🗑️ Remove", key=f"remove_{i}"):
                        st.session_state.streams = st.session_state.streams.drop(i).reset_index(drop=True)
                        save_persistent_streams(st.session_state.streams)
                        # Also remove log file if it exists
                        log_file = f"stream_{i}.log"
                        if os.path.exists(log_file):
                            os.remove(log_file)
                        st.rerun()
        else:
            st.info("No streams added yet. Use the 'Add New Stream' tab to add a stream.")
    
    with tab2:
        st.subheader("Add New Stream")
        
        # List available video files
        video_files = [f for f in os.listdir('.') if f.endswith(('.mp4', '.flv', '.avi', '.mov', '.mkv'))]
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("Video yang tersedia:")
            selected_video = st.selectbox("Pilih video", [""] + video_files) if video_files else None
            
            uploaded_file = st.file_uploader("Atau upload video baru", type=['mp4', 'flv', 'avi', 'mov', 'mkv'])
            
            if uploaded_file:
                # Save the uploaded file
                with open(uploaded_file.name, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                st.success("Video berhasil diupload!")
                video_path = uploaded_file.name
            elif selected_video:
                video_path = selected_video
            else:
                video_path = None
        
        with col2:
            stream_key = st.text_input("Stream Key", type="password")
            
            # Time picker for start time
            now = datetime.datetime.now()
            start_time = st.time_input("Start Time", value=now)
            start_time_str = start_time.strftime("%H:%M")
            
            duration = st.text_input("Duration (HH:MM:SS)", value="01:00:00")
            
            is_shorts = st.checkbox("Mode Shorts (720x1280)")
        
        if st.button("➕ Add Stream"):
            if video_path and stream_key:
                # Get just the filename from the path
                video_filename = os.path.basename(video_path)
                
                new_stream = pd.DataFrame({
                    'Video': [video_path],
                    'Durasi': [duration],
                    'Jam Mulai': [start_time_str],
                    'Streaming Key': [stream_key],
                    'Status': ['Menunggu'],
                    'Is Shorts': [is_shorts]
                })
                
                st.session_state.streams = pd.concat([st.session_state.streams, new_stream], ignore_index=True)
                save_persistent_streams(st.session_state.streams)
                st.success(f"Added stream for {video_filename}")
                st.rerun()
            else:
                if not video_path:
                    st.error("Please provide a video path")
                if not stream_key:
                    st.error("Please provide a streaming key")
    
    with tab3:
        st.subheader("Stream Logs")
        
        # Get all stream IDs that have log files
        log_files = [f for f in os.listdir('.') if f.startswith('stream_') and f.endswith('.log')]
        stream_ids = [int(f.split('_')[1].split('.')[0]) for f in log_files]
        
        if stream_ids:
            # Create options for selectbox
            stream_options = {}
            for idx in stream_ids:
                if idx in st.session_state.streams.index:
                    video_name = os.path.basename(st.session_state.streams.loc[idx, 'Video'])
                    stream_options[f"{video_name} (ID: {idx})"] = idx
            
            if stream_options:
                selected_stream = st.selectbox("Select stream to view logs", options=list(stream_options.keys()))
                selected_id = stream_options[selected_stream]
                
                # Display logs
                logs = get_stream_logs(selected_id)
                log_container = st.container()
                with log_container:
                    st.code("".join(logs))
                
                # Auto-refresh option
                auto_refresh = st.checkbox("Auto-refresh logs", value=False)
                if auto_refresh:
                    time.sleep(3)  # Wait 3 seconds
                    st.rerun()
            else:
                st.info("No logs available. Start a stream to see logs.")
        else:
            st.info("No logs available. Start a stream to see logs.")
    
    # Instructions
    with st.sidebar.expander("How to use"):
        st.markdown("""
        ### Instructions:
        
        1. **Add a Stream**: 
           - Select or upload a video
           - Enter your YouTube stream key
           - Set start time and duration
           - Check "Mode Shorts" for vertical videos
        
        2. **Manage Streams**:
           - Start/stop streams manually
           - Streams will start automatically at scheduled time
           - View logs to monitor streaming status
           - **Streams will continue running even if you refresh the page!**
        
        ### Requirements:
        
        - FFmpeg must be installed on your system
        - Videos must be in a compatible format (MP4 recommended)
        - Your network must allow outbound RTMP traffic
        
        ### Notes:
        
        - For YouTube Shorts, use vertical videos (9:16 aspect ratio)
        - Stream keys are sensitive information - keep them private
        - Multiple streams can run simultaneously, but this requires significant CPU and bandwidth
        - **NEW**: Streams now persist across page refreshes and app restarts!
        """)
    
    # Auto refresh every 30 seconds
    time.sleep(1)  # Small delay to prevent too frequent refreshing

if __name__ == '__main__':
    main()
