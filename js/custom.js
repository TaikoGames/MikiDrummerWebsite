document.addEventListener('DOMContentLoaded', function () {
    var current = location.pathname.split("/").pop(); // Get the current page filename
    document.querySelectorAll('.nav-link').forEach(function (link) {
      var linkPath = link.getAttribute('href').split("/").pop(); // Get the href filename
      if (linkPath === current) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page'); // Add aria-current attribute for accessibility
      } else {
        link.classList.remove('active');
        link.removeAttribute('aria-current');
      }
    });
  });
  

const audio = document.getElementById('audio');
const playPauseButton = document.getElementById('playPause');
const seekBar = document.getElementById('seekBar');
const currentTimeDisplay = document.getElementById('currentTime');
const durationDisplay = document.getElementById('duration');
const playPauseIcon = playPauseButton.querySelector('i');
const playlistItems = document.querySelectorAll('#playlist-songs li');
const nextButton = document.getElementById('next');
const prevButton = document.getElementById('prev');
const thumbnailImg = document.getElementById('thumbnail-img');

let currentSongIndex = 0;
let userHasInteracted = false;

// Function to initialize the player with default settings
function initializePlayer() {
    playPauseIcon.classList.remove('fa-pause');
    playPauseIcon.classList.add('fa-play');
    changeSong(currentSongIndex, false); // Load the first song without playing
}

// Function to play/pause the audio
function togglePlayPause() {
    userHasInteracted = true;  // Mark that user has interacted with the page
    if (audio.paused) {
        audio.play();
        playPauseIcon.classList.remove('fa-play');
        playPauseIcon.classList.add('fa-pause');
    } else {
        audio.pause();
        playPauseIcon.classList.remove('fa-pause');
        playPauseIcon.classList.add('fa-play');
    }
}

// Function to update the progress bar and current time
function updateProgress() {
    seekBar.value = (audio.currentTime / audio.duration) * 100;
    currentTimeDisplay.textContent = formatTime(audio.currentTime);
}

// Function to format time
function formatTime(time) {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds < 10 ? '0' + seconds : seconds}`;
}

// Function to change songs
function changeSong(index, shouldPlay = true) {
    if (index >= 0 && index < playlistItems.length) {
        currentSongIndex = index;
        audio.src = playlistItems[index].getAttribute('data-src');
        thumbnailImg.src = playlistItems[index].getAttribute('data-thumbnail'); // Update the thumbnail
        updatePlaylistUI();
        
        if (shouldPlay && userHasInteracted) {
            audio.play();
            playPauseIcon.classList.remove('fa-play');
            playPauseIcon.classList.add('fa-pause');
        } else {
            playPauseIcon.classList.remove('fa-pause');
            playPauseIcon.classList.add('fa-play');
        }
    }
}

// Function to update the playlist UI
function updatePlaylistUI() {
    playlistItems.forEach((item, index) => {
        item.classList.remove('active');
        if (index === currentSongIndex) {
            item.classList.add('active');
        }
    });
}

// Event listeners
playPauseButton.addEventListener('click', togglePlayPause);
audio.addEventListener('timeupdate', updateProgress);
seekBar.addEventListener('input', () => {
    audio.currentTime = (seekBar.value / 100) * audio.duration;
});
audio.addEventListener('loadedmetadata', () => {
    durationDisplay.textContent = formatTime(audio.duration);
});
nextButton.addEventListener('click', () => {
    changeSong(currentSongIndex + 1, userHasInteracted); // Only play if the user has interacted
});
prevButton.addEventListener('click', () => {
    changeSong(currentSongIndex - 1, userHasInteracted); // Only play if the user has interacted
});
playlistItems.forEach((item, index) => {
    item.addEventListener('click', () => {
        changeSong(index, userHasInteracted); // Only play if the user has interacted
    });
});

// Initialize player
initializePlayer();

//   video overlay
document.addEventListener('DOMContentLoaded', function() {
    const liveOverlay = document.querySelector('.live-overlay'); // Selects the first element with the class "live-overlay"
    const closeOverlayButton = document.querySelector('.close-overlay'); // Selects the first element with the class "close-overlay"

    // Event listener for closing the overlay manually
    closeOverlayButton.addEventListener('click', () => {
        liveOverlay.style.display = 'none'; // Hides the overlay
    });
});