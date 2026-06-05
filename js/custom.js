document.addEventListener('DOMContentLoaded', function () {
    // Active nav link
    var current = location.pathname.split("/").pop();
    document.querySelectorAll('.nav-link').forEach(function (link) {
        var linkPath = link.getAttribute('href').split("/").pop();
        if (linkPath === current) {
            link.classList.add('active');
            link.setAttribute('aria-current', 'page');
        } else {
            link.classList.remove('active');
            link.removeAttribute('aria-current');
        }
    });

    // Video overlay
    const liveOverlay = document.querySelector('.live-overlay');
    const closeOverlayButton = document.querySelector('.close-overlay');
    if (closeOverlayButton) {
        closeOverlayButton.addEventListener('click', () => {
            liveOverlay.style.display = 'none';
        });
    }
});

// ===================== AUDIO PLAYER =====================
const audio = document.getElementById('audio');
const playPauseButton = document.getElementById('playPause');
const seekBar = document.getElementById('seekBar');
const currentTimeDisplay = document.getElementById('currentTime');
const durationDisplay = document.getElementById('duration');
const playPauseIcon = playPauseButton.querySelector('i');
const nextButton = document.getElementById('next');
const prevButton = document.getElementById('prev');
const thumbnailImg = document.getElementById('thumbnail-img');
const playlistContainer = document.getElementById('playlist-songs');

let songs = [];
let currentSongIndex = 0;
let userHasInteracted = false;

function formatTime(time) {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds < 10 ? '0' + seconds : seconds}`;
}

function updatePlaylistUI() {
    document.querySelectorAll('#playlist-songs li').forEach((item, index) => {
        item.classList.toggle('active', index === currentSongIndex);
    });
}

function changeSong(index, shouldPlay = true) {
    if (index >= 0 && index < songs.length) {
        currentSongIndex = index;
        audio.src = songs[index].src;
        thumbnailImg.src = songs[index].thumbnail;
        updatePlaylistUI();
        if (shouldPlay && userHasInteracted) {
            audio.play();
            playPauseIcon.className = 'fas fa-pause';
        } else {
            playPauseIcon.className = 'fas fa-play';
        }
    }
}

function buildPlaylist(data) {
    songs = data.songs;
    playlistContainer.innerHTML = '';
    songs.forEach((song, index) => {
        const li = document.createElement('li');
        li.textContent = song.title;
        li.setAttribute('data-src', song.src);
        li.setAttribute('data-thumbnail', song.thumbnail);
        if (index === 0) li.classList.add('active');
        li.addEventListener('click', () => changeSong(index, userHasInteracted));
        playlistContainer.appendChild(li);
    });
    // Load first song
    audio.src = songs[0].src;
    thumbnailImg.src = songs[0].thumbnail;
    playPauseIcon.className = 'fas fa-play';
}

// Load playlist from JSON
fetch('/playlist.json')
    .then(r => r.json())
    .then(data => buildPlaylist(data))
    .catch(err => console.error('Error loading playlist:', err));

// Player controls
playPauseButton.addEventListener('click', () => {
    userHasInteracted = true;
    if (audio.paused) {
        audio.play();
        playPauseIcon.className = 'fas fa-pause';
    } else {
        audio.pause();
        playPauseIcon.className = 'fas fa-play';
    }
});

audio.addEventListener('timeupdate', () => {
    seekBar.value = (audio.currentTime / audio.duration) * 100;
    currentTimeDisplay.textContent = formatTime(audio.currentTime);
});

audio.addEventListener('loadedmetadata', () => {
    durationDisplay.textContent = formatTime(audio.duration);
});

seekBar.addEventListener('input', () => {
    audio.currentTime = (seekBar.value / 100) * audio.duration;
});

nextButton.addEventListener('click', () => changeSong(currentSongIndex + 1, userHasInteracted));
prevButton.addEventListener('click', () => changeSong(currentSongIndex - 1, userHasInteracted));

// ===================== VOLUME SLIDER =====================
const volumeButton = document.getElementById('volume');
const volumeIcon = volumeButton.querySelector('i');

const volumeSlider = document.createElement('input');
volumeSlider.type = 'range';
volumeSlider.id = 'volumeBar';
volumeSlider.min = 0;
volumeSlider.max = 1;
volumeSlider.step = 0.01;
volumeSlider.value = 1;
volumeSlider.style.cssText = 'width:80px; margin:0 8px; display:none; accent-color:#fff;';
volumeButton.parentNode.insertBefore(volumeSlider, volumeButton.nextSibling);

volumeButton.addEventListener('click', () => {
    volumeSlider.style.display = volumeSlider.style.display === 'none' ? 'inline-block' : 'none';
});

volumeSlider.addEventListener('input', () => {
    audio.volume = volumeSlider.value;
    if (audio.volume === 0) {
        volumeIcon.className = 'fas fa-volume-mute';
    } else if (audio.volume < 0.5) {
        volumeIcon.className = 'fas fa-volume-down';
    } else {
        volumeIcon.className = 'fas fa-volume-up';
    }
});

// ===================== PLAYLIST TOGGLE =====================
const playlistButton = document.getElementById('playlist');
const playlistEl = document.querySelector('.playlist');

playlistButton.addEventListener('click', () => {
    playlistEl.style.display = playlistEl.style.display === 'block' ? 'none' : 'block';
});
