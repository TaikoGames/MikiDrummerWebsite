// script.js
$(document).ready(function() {
    // Function to check streaming status
    function checkStreamingStatus() {
        // Simulate streaming status check
        // Replace this with actual streaming status check logic
        let isStreaming = true; // Set this to true or false based on actual status

        if (isStreaming) {
            $('#streaming-overlay').show();
        } else {
            $('#streaming-overlay').hide();
        }
    }

    // Check streaming status when the page loads
    checkStreamingStatus();

    // You can set an interval to check streaming status periodically
    setInterval(checkStreamingStatus, 60000); // Check every 60 seconds
});
