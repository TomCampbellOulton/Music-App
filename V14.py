# MyMusicApp_Rewritten_QOL.py
# Improved version with requested QoL features:
# 1. Persistent folders remembered
# 2. Listening history logging
# 3. Recommended playlist based on listening history
# 4. Fixed header widths in library
# 5. Save current queue as playlist
# 6. Right-click metadata editing
# 7. Seek bar for scrubbing current song
# 8. Fixed drag/drop in queue

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import Qt, Signal
import sys, os, json, random, datetime, re, threading, urllib.parse, urllib.request
from dataclasses import dataclass

# --- models ---
@dataclass
class Track:
    path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    genre: str = ""
    duration: float = 0.0

    def to_dict(self):
        return {"path": self.path, "title": self.title, "artist": self.artist, "album": self.album, "genre": self.genre, "duration": self.duration}

    @staticmethod
    def from_dict(d):
        return Track(**{k: d.get(k, "") for k in ("path","title","artist","album","genre","duration")})

# --- player (vlc wrapper) ---
import vlc
class Player(QtCore.QObject):
    trackFinished = QtCore.Signal()
    def __init__(self):
        super().__init__()
        self._vlc = vlc.Instance()
        self._mp = self._vlc.media_player_new()
        self._mp.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, self._on_end)
        self._repeat = False
    def load(self, path):
        try:
            m = self._vlc.media_new(path)
            self._mp.set_media(m)
        except Exception:
            pass
    def play(self):
        self._mp.play()
    def pause(self):
        self._mp.pause()
    def stop(self):
        self._mp.stop()
    def is_playing(self):
        return bool(self._mp.is_playing())
    def set_volume(self, v:int):
        self._mp.audio_set_volume(int(v))
    def get_position_seconds(self):
        return max(0.0, float(self._mp.get_time() or 0)/1000.0)
    def get_length_seconds(self):
        return max(0.0, float(self._mp.get_length() or 0)/1000.0)
    def seek_seconds(self,s):
        self._mp.set_time(int(s*1000))
    def toggle_repeat(self):
        self._repeat = not self._repeat
    def _on_end(self, *_):
        if self._repeat:
            self.seek_seconds(0)
            self.play()
        else:
            self.trackFinished.emit()

# --- utility: metadata ---
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, ID3NoHeaderError

def read_metadata(path):
    title = artist = album = genre = ''
    dur = 0.0
    try:
        audio = MP3(path)
        dur = float(audio.info.length or 0.0)
        try:
            eid = EasyID3(path)
            title = eid.get('title', [os.path.splitext(os.path.basename(path))[0]])[0]
            # Remove any (Lyrics) in the titles
            title = title.replace("(Lyrics)", "")
            title = title.replace("(Animated Video)", "")
            title = title.replace("(Official Video)", "")
            artist = eid.get('artist', ['Unknown Artist'])[0]
            album = eid.get('album', [''])[0]
            genre = eid.get('genre', [''])[0]
        except Exception:
            title = os.path.splitext(os.path.basename(path))[0]
    except Exception:
        title = os.path.splitext(os.path.basename(path))[0]
    return title, artist, album, genre, dur

# --- Library table ---
class LibraryPane(QtWidgets.QWidget):
    trackClicked = Signal(Track)   # NEW
    trackDoubleClicked = Signal(Track)
    playNextRequested = Signal(Track)
    checkLyricsRequested = Signal()   # <--- NEW signal
    
    def __init__(self, folders: list[str]):
        super().__init__()
        self.folders = folders

        # Toolbar
        toolbar = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton('＋ Add Folder')
        btn_add.clicked.connect(self._add_folder)
        btn_rescan = QtWidgets.QPushButton('Rescan')
        btn_rescan.clicked.connect(self.load)
        btn_check = QtWidgets.QPushButton('Check Lyrics')
        btn_check.clicked.connect(self.checkLyricsRequested.emit)  # <--- FIXED

        
        self.search = QtWidgets.QLineEdit()                           # NEW
        self.search.setPlaceholderText("Search by song or artist...") # NEW
        self.search.textChanged.connect(self._apply_filter)           # NEW
        toolbar.addWidget(btn_add)
        toolbar.addWidget(btn_rescan)
        toolbar.addWidget(btn_check)
        toolbar.addWidget(self.search)   # NEW
        toolbar.addStretch()

        # Table
        self.table = QtWidgets.QTableWidget(0,6)
        self.table.setHorizontalHeaderLabels(['Title','Artist','Album','Genre','Duration','Path'])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.SelectedClicked)
        self.table.itemClicked.connect(self._on_click)     # NEW (single-click plays)
        self.table.itemDoubleClicked.connect(self._on_double)
        #self.table.itemChanged.connect(self._on_item_changed)
        self.table.setColumnHidden(5, True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)



        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.table,1)
        self._tracks: list[Track] = []
        self.load()
        

    def _on_click(self, item):   # NEW
        row = item.row()
        self.trackClicked.emit(self._tracks[row])

    def _apply_filter(self, text):   # NEW
        text = text.lower()
        for row in range(self.table.rowCount()):
            title = self.table.item(row,0).text().lower()
            artist = self.table.item(row,1).text().lower()
            match = (text in title) or (text in artist)
            self.table.setRowHidden(row, not match)


    def _add_folder(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Add music folder")
        if d and d not in self.folders:
            self.folders.append(d)
            self.load()

    def _menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid(): 
            return
        row = idx.row()
        t = self._tracks[row]
        
        menu = QtWidgets.QMenu(self)
        menu.addAction("Like ❤️", lambda: self._like_track(t))
        menu.addAction("Add to Playlist ➕", lambda: self._add_to_playlist(t))
        menu.addSeparator()
        for field in ["title","artist","album","genre"]:
            menu.addAction(f"Edit {field.title()}", lambda f=field: self._edit_field(row,f))
        menu.exec(self.table.mapToGlobal(pos))

    def _like_track(self, track):
        liked_file = "liked_songs.json"
        data = []
        if os.path.exists(liked_file):
            with open(liked_file,"r",encoding="utf-8") as f:
                data = json.load(f)
        if track.path not in [d["path"] for d in data]:
            data.append(track.to_dict())
            with open(liked_file,"w",encoding="utf-8") as f:
                json.dump(data,f,indent=2)

    def _add_to_playlist(self, track):
        name,ok = QtWidgets.QInputDialog.getText(self,"Add to Playlist","Playlist name:")
        if ok and name:
            main = self.parentWidget().parentWidget().parentWidget().window()
            main.playlists.add_playlist(name, [track])

    def _edit_field(self,row,field):
        t = self._tracks[row]
        old = getattr(t,field)
        new,ok = QtWidgets.QInputDialog.getText(self,"Edit metadata",f"{field.title()}:",text=old)
        if ok and new:
            setattr(t,field,new)
            self.table.item(row,["title","artist","album","genre"].index(field)).setText(new)

    def tracks(self):
        return list(self._tracks)

    def _on_double(self, item):
        row = item.row()
        self.trackDoubleClicked.emit(self._tracks[row])

    def _on_item_changed(self, item):
        col_map = {0:'title',1:'artist',2:'album',3:'genre'}
        if item.column() not in col_map: return
        row = item.row()
        t = self._tracks[row]
        field = col_map[item.column()]
        new_val = item.text().strip()
        setattr(t,field,new_val)
        try:
            try:
                tags = EasyID3(t.path)
            except ID3NoHeaderError:
                audio = ID3()
                input("Trying to modify a music file")
                audio.save(t.path)
                tags = EasyID3(t.path)
            tags[field] = new_val
            print(new_val)
            input("Trying to modify a music file")
            tags.save(t.path)
        except Exception as e:
            print("Metadata save error:", e)

    # Old but SLOW for > 800 songs
    """
    def load(self):
        self.table.setRowCount(0)
        self._tracks.clear()
        print("Started Loading")
        for root in self.folders:
            for r,_,files in os.walk(root):
                for f in files:
                    if f.lower().endswith('.mp3'):
                        path = os.path.join(r,f)
                        title,artist,album,genre,dur = read_metadata(path)
                        t = Track(path,title,artist,album,genre,dur)
                        self._tracks.append(t)
                        row = self.table.rowCount()
                        self.table.insertRow(row)
                        self.table.setItem(row,0, QtWidgets.QTableWidgetItem(t.title))
                        self.table.setItem(row,1, QtWidgets.QTableWidgetItem(t.artist))
                        self.table.setItem(row,2, QtWidgets.QTableWidgetItem(t.album))
                        self.table.setItem(row,3, QtWidgets.QTableWidgetItem(t.genre))
                        self.table.setItem(row,4, QtWidgets.QTableWidgetItem(f"{int(t.duration//60)}:{int(t.duration%60):02d}"))
                        self.table.setItem(row,5, QtWidgets.QTableWidgetItem(t.path))
        print("Finished Loading")
        # fixed widths for fitting with lyrics
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.table.setColumnWidth(0,200)
        self.table.setColumnWidth(1,150)
        self.table.setColumnWidth(2,150)
        self.table.setColumnWidth(3,120)
        self.table.setColumnWidth(4,70)"""

    def load(self):
        self.table.setRowCount(0)
        self._tracks.clear()

        paths = []
        for root in self.folders:
            for r,_,files in os.walk(root):
                for f in files:
                    if f.lower().endswith('.mp3'):
                        paths.append(os.path.join(r,f))

        # Pre-allocate
        self.table.setRowCount(len(paths))

        self._tracks = []
        for row, path in enumerate(paths):
            title = os.path.splitext(os.path.basename(path))[0]
            t = Track(path, title, "Unknown Artist", "", "", 0.0)
            self._tracks.append(t)

            # Store Track in UserRole for safety
            it = QtWidgets.QTableWidgetItem(title)
            it.setData(Qt.UserRole, t)
            self.table.setItem(row,0,it)

            self.table.setItem(row,1, QtWidgets.QTableWidgetItem("Unknown Artist"))
            self.table.setItem(row,2, QtWidgets.QTableWidgetItem(""))
            self.table.setItem(row,3, QtWidgets.QTableWidgetItem(""))
            self.table.setItem(row,4, QtWidgets.QTableWidgetItem(""))
            self.table.setItem(row,5, QtWidgets.QTableWidgetItem(path))

        # Kick off metadata thread
        threading.Thread(target=self._load_metadata_async, args=(paths,), daemon=True).start()

    def _load_metadata_async(self, paths):
        for row, path in enumerate(paths):
            # Prevent out-of-range crash
            if row >= len(self._tracks):
                break

            title,artist,album,genre,dur = read_metadata(path)

            # Schedule row update on main thread
            QtCore.QMetaObject.invokeMethod(
                self, "_update_row", QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(int, row),
                QtCore.Q_ARG(str, title),
                QtCore.Q_ARG(str, artist),
                QtCore.Q_ARG(str, album),
                QtCore.Q_ARG(str, genre),
                QtCore.Q_ARG(str, f"{int(dur//60)}:{int(dur%60):02d}")
            )

    @QtCore.Slot(int,str,str,str,str,str)
    def _update_row(self, row, title, artist, album, genre, dur_str):
        if row >= self.table.rowCount():
            return  # row no longer exists
        self.table.item(row,0).setText(title)
        self.table.item(row,1).setText(artist)
        self.table.item(row,2).setText(album)
        self.table.item(row,3).setText(genre)
        self.table.item(row,4).setText(dur_str)

        # Also update Track object safely
        if row < len(self._tracks):
            t = self._tracks[row]
            t.title, t.artist, t.album, t.genre = title, artist, album, genre
            try:
                t.duration = int(dur_str.split(":")[0])*60 + int(dur_str.split(":")[1])
            except:
                t.duration = 0.0



# --- Playlists pane ---
class PlaylistsPane(QtWidgets.QWidget):
    playRequested = Signal(list)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.parent_ref = parent
        self._pls: dict[str, list[Track]] = {}
        v = QtWidgets.QVBoxLayout(self)
        h = QtWidgets.QHBoxLayout()
        btn_save = QtWidgets.QPushButton('💾 Save Queue as Playlist')
        btn_save.clicked.connect(self._save_current)
        btn_by_artist = QtWidgets.QPushButton('Auto: By Artist')
        btn_by_artist.clicked.connect(lambda: self._make_grouped('artist'))
        btn_by_genre = QtWidgets.QPushButton('Auto: By Genre')
        btn_by_genre.clicked.connect(lambda: self._make_grouped('genre'))
        btn_reco = QtWidgets.QPushButton('🔥 Recommended')
        btn_reco.clicked.connect(self._make_recommended)
        h.addWidget(btn_save); h.addWidget(btn_by_artist); h.addWidget(btn_by_genre); h.addWidget(btn_reco)
        h.addStretch(); v.addLayout(h)
        self.list = QtWidgets.QListWidget(); v.addWidget(self.list,1)
        self.list.itemDoubleClicked.connect(self._play)

    def add_playlist(self,name:str,tracks:list[Track]):
        self._pls[name]=list(tracks)
        it=QtWidgets.QListWidgetItem(name)
        it.setData(Qt.UserRole,name)
        self.list.addItem(it)

    def _save_current(self):
        main = self.parent_ref
        tracks = main._queue
        if not tracks: return
        name,ok = QtWidgets.QInputDialog.getText(self,'Playlist name','Name:')
        if ok and name:
            self.add_playlist(name,list(tracks))

    def _play(self,item):
        name=item.data(Qt.UserRole)
        self.playRequested.emit([t for t in self._pls.get(name,[])])

    def _make_grouped(self,field):
        from collections import defaultdict
        lib=self.parent_ref.library
        groups=defaultdict(list)
        for t in lib.tracks():
            key=getattr(t,field) or f'Unknown {field}'
            groups[key].append(t)
        for name,tracks in groups.items():
            self.add_playlist(f"{field.title()}: {name}",tracks)

    def _make_recommended(self):
        # History File Location
        histfile = ("my_music_history.json")
        #histfile=os.path.join(os.path.expanduser("~"),".my_music_history.json")
        if not os.path.exists(histfile):
            QtWidgets.QMessageBox.information(self,"No history","Listen to some tracks first!")
            return
        with open(histfile,"r",encoding="utf-8") as f: data=json.load(f)
        from collections import Counter
        top_artists=Counter([d["artist"] for d in data if d.get("artist")]).most_common(3)
        tracks=[]
        for artist,_ in top_artists:
            for t in self.parent_ref.library.tracks():
                if t.artist==artist: tracks.append(t)
        self.add_playlist("🔥 Recommended",tracks)

# --- Queue ---
class QueueTable(QtWidgets.QTableWidget):
    orderChanged=Signal()
    def __init__(self):
        super().__init__(0,4)
        self.setHorizontalHeaderLabels(['#','Title','Artist','Duration'])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
    def dropEvent(self,event):
        super().dropEvent(event)
        self.orderChanged.emit()

# --- Lyrics ---
class LRC:
    time_pat=re.compile(r"\[(\d{1,2}):(\d{1,2})(?:\.(\d{1,2}))?\]")
    @staticmethod
    def parse(text:str):
        out=[]
        for raw in text.splitlines():
            times=list(LRC.time_pat.finditer(raw))
            line=LRC.time_pat.sub("",raw).strip()
            for m in times:
                mm,ss=int(m.group(1)),int(m.group(2))
                cs=int(m.group(3) or 0)
                out.append((mm*60+ss+cs/100.0,line))
        return sorted(out,key=lambda x:x[0])


class LyricsPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QtWidgets.QVBoxLayout(self)
        self.browser = QtWidgets.QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet("QTextBrowser{background:transparent;border:none;padding:12px;}")
        v.addWidget(self.browser, 1)

        self.lines = []
        self.idx = -1
        self._get_time_cb = None
        self._current_track = None

        # highlight timer
        self._highlight_timer = QtCore.QTimer(self)
        self._highlight_timer.setInterval(200)
        self._highlight_timer.timeout.connect(self._tick)
        self._highlight_timer.start()

    def set_playback_callback(self, func):
        """MainWindow should pass in player.get_position_seconds"""
        self._get_time_cb = func

    def load_for(self, track: Track):
        """Load lyrics for given Track"""
        self._current_track = track
        self.lines, self.idx = [], -1
        base = os.path.splitext(track.path)[0]
        lrc = base + ".lrc"
        if os.path.exists(lrc):
            try:
                with open(lrc, "r", encoding="utf-8", errors="ignore") as f:
                    self.lines = LRC.parse(f.read())
                self._render()
                return
            except Exception:
                pass
        self.browser.setHtml("<i>Searching lyrics…</i>")
        threading.Thread(target=self._fetch_online, args=(track,), daemon=True).start()

    def _fetch_online(self, track):
        try:
            q = urllib.parse.urlencode({'artist_name': track.artist, 'track_name': track.title})
            with urllib.request.urlopen(f"https://lrclib.net/api/get?{q}", timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8') or '{}')
            synced = data.get('syncedLyrics') or data.get('lrc')
            plain = data.get('plainLyrics')
            if synced:
                self.lines = LRC.parse(synced)
                QtCore.QMetaObject.invokeMethod(self, "_render", QtCore.Qt.QueuedConnection)
                return
            if plain:
                QtCore.QMetaObject.invokeMethod(self, "_render_plain", QtCore.Qt.QueuedConnection,
                                                QtCore.Q_ARG(str, plain))
                return
        except Exception as e:
            print("Lyrics fetch error:", e)
        QtCore.QMetaObject.invokeMethod(
            self.browser, 'setHtml',
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(str, "<i>No lyrics found online.</i>")
        )

    @QtCore.Slot()
    def _render(self):
        esc = lambda s: (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        html = [f"<div id='l{i}' style='padding:4px 0;color:#bbb'>{esc(line)}</div>" for i,(_,line) in enumerate(self.lines)]
        self.browser.setHtml("<div style='font-size:15px;line-height:1.5'>" + "\n".join(html) + "</div>")

    @QtCore.Slot(str)
    def _render_plain(self, text: str):
        esc = lambda s: (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        self.browser.setHtml("<div style='white-space:pre-wrap;font-size:15px;line-height:1.5'>"+esc(text)+"</div>")

    def _tick(self):
        if not self.lines or not self._get_time_cb:
            return
        sec = float(self._get_time_cb() or 0.0)
        i = self.idx
        while i+1 < len(self.lines) and self.lines[i+1][0] <= sec:
            i += 1
        while i > 0 and self.lines[i][0] > sec:
            i -= 1
        if i != self.idx and 0 <= i < len(self.lines):
            self.idx = i
            self._highlight(i)

    
    def _highlight(self, i: int):
        esc = lambda s: (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        parts = []
        for j, (_, line) in enumerate(self.lines):
            if j == i:
                parts.append(
                    f"<div id='l{j}' style='padding:4px 0;background:#1db954;color:#000;border-radius:6px'>{esc(line)}</div>"
                )
            else:
                parts.append(
                    f"<div id='l{j}' style='padding:4px 0;color:#bbb'>{esc(line)}</div>"
                )

        html = "<div style='font-size:15px;line-height:1.5'>" + "\n".join(parts) + "</div>"
        self.browser.setHtml(html)
        self.browser.scrollToAnchor(f"l{i}")

# MyMusicApp_Rewritten_QOL.py (continued with complete MainWindow)

# --- MainWindow ---
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('My Music • Spotify-style (QOL)')
        self.resize(1100,720)
        self.player=Player()
        # Move Music State
        self._savefile = ('my_music_state.json')
        #self._savefile=os.path.join(os.path.expanduser('~'),'.my_music_state.json')
        # Default to music folder in same folder as this program
        #folders=[os.path.abspath('music')] if os.path.exists('music') else []
        user_music = os.path.join(os.path.expanduser("~"), "Music")
        folders = []
        if os.path.exists('music'):
            print("Loading Music Folder")
            folders.append(os.path.abspath('music'))
        if os.path.exists(user_music):
            print("Loading Systems Music Folder")
            folders.append(os.path.abspath(user_music))
            
        self.library=LibraryPane(folders)
        self.playlists=PlaylistsPane(self)
        self.lyrics=LyricsPanel(); self.lyrics.set_playback_callback(self.player.get_position_seconds)
        self.queue_table=QueueTable(); self.queue_table.orderChanged.connect(self._rebuild_queue_from_table)

        left=QtWidgets.QTabWidget(); left.addTab(self.library,'Library'); left.addTab(self.playlists,'Playlists')
        right=QtWidgets.QTabWidget(); right.addTab(self.lyrics,'Lyrics'); right.addTab(self.queue_table,'Queue')

        splitter=QtWidgets.QSplitter(); splitter.addWidget(left); splitter.addWidget(right); splitter.setSizes([700,400])
        wrapper=QtWidgets.QWidget(); v=QtWidgets.QVBoxLayout(wrapper); v.addWidget(splitter)
        self._build_player_bar(); v.addLayout(self.player_bar_layout); self.setCentralWidget(wrapper)

        # signals
        self.library.trackClicked.connect(self.play_track)  # NEW: single-click plays
        self.library.trackDoubleClicked.connect(self.play_track)
        self.playlists.playRequested.connect(self.play_playlist)
        self.player.trackFinished.connect(self._on_track_end)
        self.library.checkLyricsRequested.connect(self._check_missing_lyrics)


        # Queue single-click play
        self.queue_table.itemClicked.connect(self._play_from_queue)  # NEW
        
        self._queue=[]; self._play_index=0
        self._load_state()

    def _play_from_queue(self, item):   # NEW
        row = item.row()
        if 0 <= row < len(self._queue):
            self._play_index = row
            self._play_current()
            
    def _check_missing_lyrics(self):
        missing = []
        for t in self.library.tracks():
            base = os.path.splitext(t.path)[0]
            lrc = base + ".lrc"
            if not os.path.exists(lrc):
                try:
                    q = urllib.parse.urlencode({'artist_name': t.artist, 'track_name': t.title})
                    with urllib.request.urlopen(f"https://lrclib.net/api/get?{q}", timeout=10) as resp:
                        data = json.loads(resp.read().decode('utf-8') or '{}')
                    if not (data.get("syncedLyrics") or data.get("lrc") or data.get("plainLyrics")):
                        missing.append(t)
                except:
                    missing.append(t)

        with open("lyrics_missing_debug.json","w",encoding="utf-8") as f:
            json.dump([t.to_dict() for t in missing], f, indent=2)

        QtWidgets.QMessageBox.information(
            self,
            "Check Complete",
            f"{len(missing)} songs missing lyrics. See lyrics_missing_debug.json"
        )


    def _build_player_bar(self):
        self.player_bar_layout=QtWidgets.QHBoxLayout()
        self.prevBtn=QtWidgets.QPushButton('⏮')
        self.playBtn=QtWidgets.QPushButton('▶')
        self.nextBtn=QtWidgets.QPushButton('⏭')
        self.prevBtn.clicked.connect(self.prev_track)
        self.playBtn.clicked.connect(self.toggle_play)
        self.nextBtn.clicked.connect(self.next_track)
        self.seek=QtWidgets.QSlider(Qt.Horizontal); self.seek.setRange(0,1000)
        self.seek.sliderReleased.connect(self._seek_to)
        self._tick=QtCore.QTimer(self); self._tick.setInterval(500); self._tick.timeout.connect(self._refresh_seek); self._tick.start()
        self.vol=QtWidgets.QSlider(Qt.Horizontal); self.vol.setRange(0,100); self.vol.setValue(80); self.vol.valueChanged.connect(self.player.set_volume)
        self.now_label=QtWidgets.QLabel('—')
        self.player_bar_layout.addWidget(self.prevBtn); self.player_bar_layout.addWidget(self.playBtn); self.player_bar_layout.addWidget(self.nextBtn)
        self.player_bar_layout.addWidget(self.seek,1); self.player_bar_layout.addWidget(self.now_label); self.player_bar_layout.addStretch(); self.player_bar_layout.addWidget(self.vol)

    def _seek_to(self):
        length=float(self.player.get_length_seconds() or 0.0)
        pos=self.seek.value()/1000.0; self.player.seek_seconds(pos*length)
    def _refresh_seek(self):
        length=float(self.player.get_length_seconds() or 0.0)
        if length>0:
            pos=self.player.get_position_seconds()
            self.seek.blockSignals(True); self.seek.setValue(int((pos/length)*1000)); self.seek.blockSignals(False)



    # Old
    """
    def _sync_queue_table(self):
        self.queue_table.setRowCount(0)
        for i,t in enumerate(self._queue):
            r=self.queue_table.rowCount(); self.queue_table.insertRow(r)
            self.queue_table.setItem(r,0,QtWidgets.QTableWidgetItem(str(i+1)))
            self.queue_table.setItem(r,1,QtWidgets.QTableWidgetItem(t.title))
            self.queue_table.setItem(r,2,QtWidgets.QTableWidgetItem(t.artist))
            self.queue_table.setItem(r,3,QtWidgets.QTableWidgetItem(f"{int(t.duration//60)}:{int(t.duration%60):02d}"))
        self.queue_table.resizeColumnsToContents()"""
    def _sync_queue_table(self):
        self.queue_table.setRowCount(0)
        for i,t in enumerate(self._queue):
            r=self.queue_table.rowCount()
            self.queue_table.insertRow(r)

            # Store Track in column 0’s data
            it = QtWidgets.QTableWidgetItem(str(i+1))
            it.setData(Qt.UserRole, t)   # <--- actual Track object
            self.queue_table.setItem(r,0,it)

            self.queue_table.setItem(r,1,QtWidgets.QTableWidgetItem(t.title))
            self.queue_table.setItem(r,2,QtWidgets.QTableWidgetItem(t.artist))
            self.queue_table.setItem(r,3,QtWidgets.QTableWidgetItem(
                f"{int(t.duration//60)}:{int(t.duration%60):02d}"
            ))
        self.queue_table.resizeColumnsToContents()


    # Old
    """
    def _rebuild_queue_from_table(self):
        newq=[]; lib_tracks=self.library.tracks()
        for r in range(self.queue_table.rowCount()):
            title_item=self.queue_table.item(r,1); artist_item=self.queue_table.item(r,2)
            if not title_item or not artist_item: continue
            title,artist=title_item.text(),artist_item.text()
            candidate=next((x for x in lib_tracks if x.title==title and x.artist==artist),None)
            if candidate: newq.append(candidate)
        if newq:
            self._queue=newq; self._play_index=min(self._play_index,len(self._queue)-1)
        self._sync_queue_table()"""
    # New
    def _rebuild_queue_from_table(self):
        newq=[]
        for r in range(self.queue_table.rowCount()):
            item = self.queue_table.item(r,0)
            if not item:
                continue
            t = item.data(Qt.UserRole)
            if t:
                newq.append(t)

        if newq:
            self._queue = newq
            self._play_index = min(self._play_index, len(self._queue)-1)




    def play_track(self,t:Track):
        allt=self.library.tracks()
        try:
            idx=next(i for i,x in enumerate(allt) if x.path==t.path)
            self._queue=allt[idx:]+allt[:idx]
        except StopIteration:
            self._queue=[t]
        self._play_index=0; self._play_current(); self._sync_queue_table()

    def play_playlist(self,tracks:list[Track]):
        if not tracks: return
        self._queue=list(tracks); self._play_index=0; self._play_current(); self._sync_queue_table()

    def prev_track(self):
        if not self._queue: return
        if self.player.get_position_seconds()>3:
            self.player.seek_seconds(0); return
        self._play_index=max(0,self._play_index-1); self._play_current()

    def next_track(self):
        if not self._queue: return
        self._play_index=min(len(self._queue)-1,self._play_index+1); self._play_current()

    def _on_track_end(self):
        self.next_track()

    def _play_current(self):
        if not self._queue: return
        t=self._queue[self._play_index]
        self.player.load(t.path); self.player.play(); self.playBtn.setText('⏸')
        self.now_label.setText(f"Now: {t.title} — {t.artist}")
        self._sync_queue_table(); self.lyrics.load_for(t); self._log_play(t)

    def toggle_play(self):
        if self.player.is_playing(): self.player.pause(); self.playBtn.setText('▶')
        else: self.player.play(); self.playBtn.setText('⏸')

    def _log_play(self,t:Track):
        histfile=os.path.join(os.path.expanduser("~"),".my_music_history.json")
        entry={"path":t.path,"title":t.title,"artist":t.artist,"time":datetime.datetime.now().isoformat()}
        try:
            data=[]; 
            if os.path.exists(histfile):
                with open(histfile,"r",encoding="utf-8") as f: data=json.load(f)
            data.append(entry)
            with open(histfile,"w",encoding="utf-8") as f: json.dump(data,f,indent=2)
        except Exception as e: print("History log error:",e)

    def _load_state(self):
        if os.path.exists(self._savefile):
            try:
                with open(self._savefile,'r',encoding='utf-8') as f: data=json.load(f)
                folders=data.get('folders',[])
                if folders: self.library.folders=folders; self.library.load()
                pls=data.get('playlists',{})
                for name,arr in pls.items(): self.playlists.add_playlist(name,[Track.from_dict(x) for x in arr])
                q=data.get('queue',[])
                if q: self._queue=[Track.from_dict(x) for x in q]; self._play_index=min(data.get('play_index',0),len(self._queue)-1); self._sync_queue_table()
            except Exception as e: print('Failed to load state',e)

    def _save_state(self):
        try:
            data={}
            data['folders']=self.library.folders
            data['playlists']={k:[t.to_dict() for t in v] for k,v in self.playlists._pls.items()}
            data['queue']=[t.to_dict() for t in self._queue]
            data['play_index']=self._play_index
            with open(self._savefile,'w',encoding='utf-8') as f: json.dump(data,f,indent=2)
        except Exception as e: print('Failed to save state',e)

# --- run ---
if __name__=='__main__':
    app=QtWidgets.QApplication(sys.argv)
    w=MainWindow(); app.aboutToQuit.connect(w._save_state); w.show(); sys.exit(app.exec())
