// static/watch.js
window.initWatch = function(videoId, credit) {
  const vid = document.getElementById("video");
  const status = document.getElementById("status");
  let credited = false;

  function tryCredit() {
    if (credited) return;
    const duration = vid.duration || 30;
    const watched = Math.floor(vid.currentTime || 0);
    // Only credit if watched >= 80% of duration
    if (watched >= 0.8 * duration) {
      // POST to server
      fetch("/api/report_watch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_id: videoId, watched_seconds: watched, video_duration: Math.floor(duration) })
      }).then(r => r.json()).then(js => {
        if (js.status === "ok" || js.status === "credited") {
          status.textContent = "Credited: $" + credit;
          credited = true;
        } else {
          status.textContent = "Not credited: " + (js.message || js.status);
        }
      }).catch(e => {
        status.textContent = "Error reporting watch";
      });
    } else {
      status.textContent = "Watch at least 80% to get credit. Watched: " + Math.floor(vid.currentTime) + "s";
    }
  }

  // When video ends, try credit
  vid.addEventListener("ended", function() {
    tryCredit();
  });

  // Also allow manual credit attempt every 5s while playing if already >=80%
  setInterval(function() {
    if (!credited && !isNaN(vid.duration)) {
      const duration = vid.duration;
      const watched = vid.currentTime;
      if (watched >= 0.8 * duration) {
        tryCredit();
      }
    }
  }, 5000);
};
