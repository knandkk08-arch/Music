import os
import asyncio
import subprocess
import uuid
import threading
import glob as globmod
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = "8330954224:AAF7CKlLbVY0vQp2qGt6yYOL5nB4QnB5VqY"

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

SUPPORTED_DOMAINS = [
    'youtube.com', 'youtu.be',
    'instagram.com',
    'twitter.com', 'x.com',
    'facebook.com', 'fb.watch',
    'tiktok.com',
    'reddit.com',
    'pinterest.com', 'pin.it',
    'vimeo.com',
    'dailymotion.com',
    'soundcloud.com',
    'twitch.tv',
    'snapchat.com',
    'threads.net',
    'linkedin.com',
]


def is_supported_link(text):
    text_lower = text.lower().strip()
    if not ('http://' in text_lower or 'https://' in text_lower or 'www.' in text_lower):
        return False
    for domain in SUPPORTED_DOMAINS:
        if domain in text_lower:
            return True
    return False


def is_youtube_link(text):
    text_lower = text.lower().strip()
    return 'youtube.com' in text_lower or 'youtu.be' in text_lower


def get_platform_name(url):
    url_lower = url.lower()
    platforms = {
        'instagram.com': 'Instagram',
        'twitter.com': 'Twitter/X',
        'x.com': 'Twitter/X',
        'facebook.com': 'Facebook',
        'fb.watch': 'Facebook',
        'tiktok.com': 'TikTok',
        'reddit.com': 'Reddit',
        'pinterest.com': 'Pinterest',
        'pin.it': 'Pinterest',
        'vimeo.com': 'Vimeo',
        'dailymotion.com': 'Dailymotion',
        'soundcloud.com': 'SoundCloud',
        'twitch.tv': 'Twitch',
        'snapchat.com': 'Snapchat',
        'threads.net': 'Threads',
        'linkedin.com': 'LinkedIn',
        'youtube.com': 'YouTube',
        'youtu.be': 'YouTube',
    }
    for domain, name in platforms.items():
        if domain in url_lower:
            return name
    return 'Unknown'


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    first_name = user.first_name or "Friend"

    welcome_message = (
        f"Hey {first_name} 👋\n\n"
        "I can download music & videos for you!\n\n"
        "🔍 Send a song name\n"
        "🔗 Or paste a link from:\n"
        "     YouTube | Instagram | TikTok\n\n"
        "That's it, try it! 🎶"
    )
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 HELP GUIDE\n"
        "═════════════════\n\n"
        "Option 1: Search by Song Name\n"
        "┌─────────────────────────\n"
        "│ Just type the song name!\n"
        '│ Example: Blinding Lights\n'
        "│ I'll show you top 6 results\n"
        "│ Pick the one you want\n"
        "└─────────────────────────\n\n"
        "Option 2: Paste a Link\n"
        "┌─────────────────────────\n"
        "│ Paste a link from:\n"
        "│ YouTube, Instagram, Twitter/X,\n"
        "│ Facebook, TikTok, Reddit,\n"
        "│ Pinterest, Vimeo, SoundCloud,\n"
        "│ Dailymotion & more!\n"
        "└─────────────────────────\n\n"
        "Download Options:\n"
        "🎵 Audio - High Quality MP3 (320kbps)\n"
        "🎬 Video - Best Quality MP4\n\n"
        "Features:\n"
        "✨ Instant search results\n"
        "✨ Real-time download progress\n"
        "✨ Audio & Video downloads\n"
        "✨ Multi-platform support\n"
        "✨ Best quality available\n\n"
        "Need Help?\n"
        "Just send me a song name or link!"
    )
    await update.message.reply_text(help_text)


def format_duration(duration):
    try:
        if duration is None:
            return "Unknown"
        duration = int(duration)
        mins = duration // 60
        secs = duration % 60
        return f"{mins}:{secs:02d}"
    except Exception:
        return "Unknown"


def compress_audio(input_file, output_file, bitrate="32k"):
    try:
        cmd = [
            'ffmpeg', '-i', input_file, '-b:a', bitrate, '-ac', '2',
            '-ar', '22050', '-q:a', '9', output_file, '-y'
        ]
        subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        return True
    except Exception:
        return False


def shorten_title(title):
    separators = ['|', ' - ', ' Full Song', ' Official', '(', 'Lyrics', '｜']
    for sep in separators:
        if sep in title:
            title = title.split(sep)[0].strip()
    if len(title) > 60:
        title = title[:60].strip()
    return title


def make_progress_bar(percent):
    filled = int(percent / 5)
    empty = 20 - filled
    bar = "🟩" * filled + "⬜" * empty
    return bar


async def _animate_initial_progress(status_msg):
    steps = [5, 10, 15, 20]
    for pct in steps:
        text = _build_progress_text(pct)
        try:
            await status_msg.edit_text(text)
        except Exception:
            pass
        await asyncio.sleep(0.25)


def create_progress_hook(progress_data, lock):
    def hook(d):
        with lock:
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)

                if total > 0:
                    percent = (downloaded / total) * 100
                else:
                    percent = 0

                progress_data['percent'] = percent
                progress_data['updated'] = True
                progress_data['snapshots'].append(int(percent))

            elif d['status'] == 'finished':
                progress_data['percent'] = 100
                progress_data['finished'] = True
                progress_data['updated'] = True

    return hook


def _make_progress_data():
    return (
        {'percent': 0, 'updated': False, 'finished': False, 'error': False, 'snapshots': [], 'last_shown_pct': -1},
        threading.Lock(),
    )


async def _stop_progress_task(task, progress_data):
    progress_data['finished'] = True
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _build_progress_text(percent):
    bar = make_progress_bar(percent)
    pct_int = int(percent)
    return f"{bar} {pct_int}%"


async def _replay_progress(status_msg, progress_data, lock):
    with lock:
        snapshots = list(progress_data['snapshots'])
        already_shown_pct = progress_data.get('last_shown_pct', -1)

    if not snapshots:
        return

    max_snapshot = max(snapshots)
    if max_snapshot <= already_shown_pct:
        return

    milestones = [25, 40, 55, 70, 85, 100]

    for milestone in milestones:
        if milestone <= already_shown_pct:
            continue
        if milestone > max_snapshot:
            continue

        best = None
        for pct in snapshots:
            if pct >= milestone and (best is None or pct <= best):
                best = pct

        if best is not None:
            text = _build_progress_text(best)
            with lock:
                progress_data['last_shown_pct'] = best
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass
            await asyncio.sleep(0.35)


async def update_progress_message(status_msg, progress_data, lock):
    last_text = ""

    while not progress_data.get('finished') and not progress_data.get('error'):
        with lock:
            updated = progress_data.get('updated', False)
            percent = progress_data.get('percent', 0)
            if updated:
                progress_data['updated'] = False

        if updated:
            text = _build_progress_text(percent)

            if text != last_text:
                last_text = text
                with lock:
                    progress_data['last_shown_pct'] = int(percent)
                try:
                    await status_msg.edit_text(text)
                except Exception:
                    pass

        await asyncio.sleep(0.4)


async def search_and_show_results(query, update, context):
    search_msg = await update.message.reply_text(f"🔍 Searching for: {query}...")

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch6:{query}", download=False)

            if not search_results or 'entries' not in search_results:
                await search_msg.edit_text("❌ No results found!")
                return

            keyboard = []
            message_text = "🎵 Search Results\n\n"

            video_ids = []

            if 'title_cache' not in context.user_data:
                context.user_data['title_cache'] = {}

            for idx, entry in enumerate(search_results['entries'][:6], 1):
                title = entry.get('title', 'Unknown')
                video_id = entry.get('id', '')
                view_count = entry.get('view_count', 0)
                video_ids.append(video_id)
                context.user_data['title_cache'][video_id] = title

                if view_count:
                    if view_count >= 1000000:
                        views_str = f"{view_count // 1000000}M views"
                    elif view_count >= 1000:
                        views_str = f"{view_count // 1000}K views"
                    else:
                        views_str = f"{view_count} views"
                else:
                    views_str = ""

                display_title = title[:50] + "..." if len(title) > 50 else title

                if views_str:
                    message_text += f"{idx}. {display_title}\n   {views_str}\n\n"
                else:
                    message_text += f"{idx}. {display_title}\n\n"

            first_row = []
            for i in range(min(4, len(video_ids))):
                first_row.append(InlineKeyboardButton(f"{i+1}", callback_data=f"sel_{video_ids[i]}"))
            if first_row:
                keyboard.append(first_row)

            second_row = []
            for i in range(4, len(video_ids)):
                second_row.append(InlineKeyboardButton(f"{i+1}", callback_data=f"sel_{video_ids[i]}"))
            second_row.append(InlineKeyboardButton("❌ Not in the list", callback_data="not_in_list"))
            if second_row:
                keyboard.append(second_row)

            reply_markup = InlineKeyboardMarkup(keyboard)
            await search_msg.edit_text(message_text, reply_markup=reply_markup)

    except Exception as e:
        try:
            await search_msg.edit_text(f"❌ Error: {str(e)[:200]}")
        except Exception:
            pass


async def search_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide a song name!\nExample: /search Song Name")
        return

    query = ' '.join(context.args)
    await search_and_show_results(query, update, context)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()

    if is_supported_link(message_text):
        await handle_link(update, context)
        return

    await search_and_show_results(message_text, update, context)


async def not_in_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📝 Please paste a link:\n\n"
        "Supported platforms:\n"
        "• YouTube, Instagram, Twitter/X\n"
        "• Facebook, TikTok, Reddit\n"
        "• Pinterest, Vimeo & more!"
    )


async def show_download_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    video_id = query.data.replace('sel_', '')

    title_cache = context.user_data.get('title_cache', {})
    title = title_cache.get(video_id, None)

    if not title:
        await query.edit_message_text("🔍 Loading...")
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {'youtube': {'player_client': ['default', 'tv', 'tv_embedded']}},
                'age_limit': 100,
            }
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: _extract_info_no_download(ydl_opts, f"https://www.youtube.com/watch?v={video_id}"))
            title = info.get('title', 'Unknown')
        except Exception:
            title = "Unknown"

    keyboard = [
        [
            InlineKeyboardButton("🎵 Download Music", callback_data=f"dla_{video_id}"),
            InlineKeyboardButton("🎬 Download Video", callback_data=f"dlv_{video_id}"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back_search")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(f"🎵 {title}", reply_markup=reply_markup)


def _store_url(context, url):
    if 'url_map' not in context.user_data:
        context.user_data['url_map'] = {}
    key = uuid.uuid4().hex[:10]
    context.user_data['url_map'][key] = url
    return key


def _resolve_url(context, key):
    url_map = context.user_data.get('url_map', {})
    if key in url_map:
        return url_map[key]
    return f"https://www.youtube.com/watch?v={key}"


def _is_stored_url(context, key):
    url_map = context.user_data.get('url_map', {})
    return key in url_map


async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    video_id = query.data.replace('dla_', '')
    video_url = _resolve_url(context, video_id)

    status_msg = await query.edit_message_text("⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ 0%")
    await _animate_initial_progress(status_msg)

    session_id = uuid.uuid4().hex[:8]
    session_dir = os.path.join(DOWNLOAD_FOLDER, session_id)
    os.makedirs(session_dir, exist_ok=True)

    progress_data, lock = _make_progress_data()
    progress_data['last_shown_pct'] = 20
    progress_task = None

    try:
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'outtmpl': os.path.join(session_dir, '%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'nopostoverwrites': False,
            'socket_timeout': 60,
            'source_address': '0.0.0.0',
            'skip_unavailable_fragments': True,
            'fragment_retries': 10,
            'retries': 10,
            'extractor_args': {'youtube': {'player_client': ['default', 'tv', 'tv_embedded']}},
            'age_limit': 100,
            'progress_hooks': [create_progress_hook(progress_data, lock)],
            'buffersize': 1024,
            'http_chunk_size': 1048576,
        }

        progress_task = asyncio.create_task(update_progress_message(status_msg, progress_data, lock))

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: _download_with_ytdlp(ydl_opts, video_url))
        title = info.get('title', 'audio')
        actual_id = info.get('id', video_id)

        await _stop_progress_task(progress_task, progress_data)
        progress_task = None

        await _replay_progress(status_msg, progress_data, lock)

        filename = os.path.join(session_dir, f"{actual_id}.mp3")

        if not os.path.exists(filename):
            all_files = globmod.glob(os.path.join(session_dir, '*.mp3'))
            if all_files:
                filename = all_files[0]

        if not os.path.exists(filename):
            all_files = globmod.glob(os.path.join(session_dir, '*'))
            if all_files:
                filename = all_files[0]

        if os.path.exists(filename):
            file_size = os.path.getsize(filename)
            max_size = 50 * 1024 * 1024

            final_file = filename

            if file_size > max_size:
                compressed_file = os.path.join(session_dir, f"{actual_id}_compressed.mp3")

                if compress_audio(filename, compressed_file, bitrate="32k"):
                    final_file = compressed_file
                    file_size = os.path.getsize(final_file)

                    if file_size > max_size:
                        ultra_file = os.path.join(session_dir, f"{actual_id}_ultra.mp3")
                        if compress_audio(filename, ultra_file, bitrate="16k"):
                            final_file = ultra_file
                            file_size = os.path.getsize(final_file)

            if file_size <= max_size and os.path.exists(final_file):
                short_title = shorten_title(title)

                try:
                    await status_msg.edit_text("🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 100%")
                except Exception:
                    pass

                with open(final_file, 'rb') as audio:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=audio,
                        title=short_title,
                        caption=f"🎵 {short_title}\n\n✅ Complete!",
                    )
            elif file_size > max_size:
                await query.message.reply_text("❌ File still too large even after compression. Try a shorter video.")

            _cleanup_dir(session_dir)
        else:
            try:
                await status_msg.edit_text("❌ Download failed: Could not process file")
            except Exception:
                await query.message.reply_text("❌ Download failed: Could not process file")

        try:
            await status_msg.delete()
        except Exception:
            pass

    except asyncio.TimeoutError:
        progress_data['error'] = True
        if progress_task:
            await _stop_progress_task(progress_task, progress_data)
        try:
            await status_msg.edit_text("❌ Download failed: Timed out. Please try again.")
        except Exception:
            pass
        _cleanup_dir(session_dir)
    except Exception as e:
        progress_data['error'] = True
        if progress_task:
            await _stop_progress_task(progress_task, progress_data)
        display_error = _format_download_error(str(e))
        try:
            await status_msg.edit_text(f"❌ {display_error}")
        except Exception:
            try:
                await query.message.reply_text(f"❌ {display_error}")
            except Exception:
                pass
        _cleanup_dir(session_dir)


async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    video_id = query.data.replace('dlv_', '')
    video_url = _resolve_url(context, video_id)

    status_msg = await query.edit_message_text("⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ 0%")
    await _animate_initial_progress(status_msg)

    session_id = uuid.uuid4().hex[:8]
    session_dir = os.path.join(DOWNLOAD_FOLDER, session_id)
    os.makedirs(session_dir, exist_ok=True)

    progress_data, lock = _make_progress_data()
    progress_data['last_shown_pct'] = 20
    progress_task = None

    is_yt = is_youtube_link(video_url)

    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best[height<=720]' if is_yt else 'best[ext=mp4][height<=720]/best[height<=720]/best',
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(session_dir, '%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 60,
            'source_address': '0.0.0.0',
            'skip_unavailable_fragments': True,
            'fragment_retries': 10,
            'retries': 10,
            'extractor_args': {'youtube': {'player_client': ['default', 'tv', 'tv_embedded']}},
            'age_limit': 100,
            'progress_hooks': [create_progress_hook(progress_data, lock)],
            'buffersize': 1024,
            'http_chunk_size': 1048576,
        }

        progress_task = asyncio.create_task(update_progress_message(status_msg, progress_data, lock))

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: _download_with_ytdlp(ydl_opts, video_url))
        title = info.get('title', 'video')
        actual_id = info.get('id', video_id)

        await _stop_progress_task(progress_task, progress_data)
        progress_task = None

        await _replay_progress(status_msg, progress_data, lock)

        filename = _find_video_file(session_dir, actual_id)

        if os.path.exists(filename):
            file_size = os.path.getsize(filename)
            max_size = 50 * 1024 * 1024

            if file_size <= max_size:
                short_title = shorten_title(title)

                try:
                    await status_msg.edit_text("🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 100%")
                except Exception:
                    pass

                with open(filename, 'rb') as video_file:
                    await context.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=video_file,
                        caption=f"🎬 {short_title}\n\n✅ Complete!",
                        supports_streaming=True,
                    )
            else:
                try:
                    await status_msg.edit_text("🔄 Video too large, trying 480p...")
                except Exception:
                    pass
                await asyncio.sleep(1)

                try:
                    await status_msg.edit_text("⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ 0%")
                except Exception:
                    pass
                await _animate_initial_progress(status_msg)

                _cleanup_dir(session_dir)
                os.makedirs(session_dir, exist_ok=True)

                progress_data_retry, lock_retry = _make_progress_data()
                progress_data_retry['last_shown_pct'] = 20

                ydl_opts_low = {
                    'format': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]' if is_yt else 'best[ext=mp4][height<=480]/best[height<=480]/best',
                    'merge_output_format': 'mp4',
                    'outtmpl': os.path.join(session_dir, '%(id)s.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                    'socket_timeout': 60,
                    'source_address': '0.0.0.0',
                    'skip_unavailable_fragments': True,
                    'fragment_retries': 10,
                    'retries': 10,
                    'extractor_args': {'youtube': {'player_client': ['default', 'tv', 'tv_embedded']}},
                    'age_limit': 100,
                    'progress_hooks': [create_progress_hook(progress_data_retry, lock_retry)],
                    'buffersize': 1024,
                    'http_chunk_size': 1048576,
                }

                progress_task = asyncio.create_task(update_progress_message(status_msg, progress_data_retry, lock_retry))

                await loop.run_in_executor(None, lambda: _download_with_ytdlp(ydl_opts_low, video_url))

                await _stop_progress_task(progress_task, progress_data_retry)
                progress_task = None

                await _replay_progress(status_msg, progress_data_retry, lock_retry)

                retry_filename = _find_video_file(session_dir, actual_id)

                if os.path.exists(retry_filename):
                    retry_size = os.path.getsize(retry_filename)
                    if retry_size <= max_size:
                        short_title = shorten_title(title)
                        try:
                            await status_msg.edit_text("🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 100%")
                        except Exception:
                            pass
                        with open(retry_filename, 'rb') as video_file:
                            await context.bot.send_video(
                                chat_id=query.message.chat_id,
                                video=video_file,
                                caption=f"🎬 {short_title} (480p)\n\n✅ Complete!",
                                supports_streaming=True,
                            )
                    else:
                        retry_size_mb = retry_size / (1024 * 1024)
                        await query.message.reply_text(
                            f"❌ Video is too large ({retry_size_mb:.0f}MB) even at 480p.\n"
                            "Telegram limit is 50MB. Try a shorter video."
                        )
                else:
                    await query.message.reply_text("❌ Download failed: Could not process video")

            _cleanup_dir(session_dir)
        else:
            try:
                await status_msg.edit_text("❌ Download failed: Could not process video")
            except Exception:
                await query.message.reply_text("❌ Download failed: Could not process video")
            _cleanup_dir(session_dir)

        try:
            await status_msg.delete()
        except Exception:
            pass

    except asyncio.TimeoutError:
        progress_data['error'] = True
        if progress_task:
            await _stop_progress_task(progress_task, progress_data)
        try:
            await status_msg.edit_text("❌ Download failed: Timed out. Please try again.")
        except Exception:
            pass
        _cleanup_dir(session_dir)
    except Exception as e:
        progress_data['error'] = True
        if progress_task:
            await _stop_progress_task(progress_task, progress_data)
        display_error = _format_download_error(str(e))
        try:
            await status_msg.edit_text(f"❌ {display_error}")
        except Exception:
            try:
                await query.message.reply_text(f"❌ {display_error}")
            except Exception:
                pass
        _cleanup_dir(session_dir)


def _download_with_ytdlp(ydl_opts, url):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=True)


def _extract_info_no_download(ydl_opts, url):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def _find_video_file(session_dir, video_id):
    filename = os.path.join(session_dir, f"{video_id}.mp4")
    if os.path.exists(filename):
        return filename
    all_files = globmod.glob(os.path.join(session_dir, '*.mp4'))
    if all_files:
        return all_files[0]
    all_files = globmod.glob(os.path.join(session_dir, '*.mkv'))
    if all_files:
        return all_files[0]
    all_files = globmod.glob(os.path.join(session_dir, '*'))
    audio_exts = {'.mp3', '.m4a', '.wav', '.ogg'}
    video_files = [f for f in all_files if not any(f.endswith(ext) for ext in audio_exts)]
    if video_files:
        return video_files[0]
    if all_files:
        return all_files[0]
    return filename


def _format_download_error(error_msg):
    if "403" in error_msg or "Forbidden" in error_msg:
        return "Video not available. Try another song."
    if "Request Entity Too Large" in error_msg:
        return "File too large for Telegram. Try a shorter video."
    if "unavailable" in error_msg.lower():
        return "This video is unavailable. Try another one."
    if "Private video" in error_msg:
        return "This is a private video and cannot be downloaded."
    if "Sign in" in error_msg:
        return "This video is age-restricted. Please try a different video."
    return error_msg[:100]


def _cleanup_dir(dirpath):
    try:
        for f in os.listdir(dirpath):
            filepath = os.path.join(dirpath, f)
            try:
                os.remove(filepath)
            except Exception:
                pass
        os.rmdir(dirpath)
    except Exception:
        pass


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()
    platform = get_platform_name(message_text)

    status_msg = await update.message.reply_text(f"🔍 Processing your {platform} link...")

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': {'player_client': ['default', 'tv', 'tv_embedded']}},
            'age_limit': 100,
        }

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: _extract_info_no_download(ydl_opts, message_text))
        title = info.get('title', 'Unknown')
        video_id = info.get('id', '')

        if is_youtube_link(message_text):
            cb_key = video_id
        else:
            cb_key = _store_url(context, message_text)

        keyboard = [
            [
                InlineKeyboardButton("🎵 Download Music", callback_data=f"dla_{cb_key}"),
                InlineKeyboardButton("🎬 Download Video", callback_data=f"dlv_{cb_key}"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await status_msg.edit_text(f"🎵 {title}", reply_markup=reply_markup)

    except Exception as e:
        error_msg = str(e)[:200]
        if 'Unsupported URL' in error_msg or 'No video formats' in error_msg:
            error_msg = f"This {platform} link is not supported or the content is private/unavailable."
        try:
            await status_msg.edit_text(f"❌ {error_msg}")
        except Exception:
            pass


async def back_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔍 Send me a song name or paste a link to search again!"
    )


def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search_song))
    application.add_handler(CallbackQueryHandler(show_download_options, pattern="^sel_"))
    application.add_handler(CallbackQueryHandler(download_audio, pattern="^dla_"))
    application.add_handler(CallbackQueryHandler(download_video, pattern="^dlv_"))
    application.add_handler(CallbackQueryHandler(not_in_list_callback, pattern="^not_in_list$"))
    application.add_handler(CallbackQueryHandler(back_search_callback, pattern="^back_search$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot started successfully!")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
