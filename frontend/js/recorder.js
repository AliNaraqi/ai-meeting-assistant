/** Browser MediaRecorder with chunk persistence in IndexedDB. */

const DB_NAME = "ama-recorder";
const STORE = "chunks";

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function saveChunk(sessionId, blob, index) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).add({ sessionId, index, blob, createdAt: Date.now() });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function clearSession(sessionId) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    const request = store.openCursor();
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) return;
      if (cursor.value.sessionId === sessionId) {
        cursor.delete();
      }
      cursor.continue();
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

function pickMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  for (const type of candidates) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(type)) {
      return type;
    }
  }
  return "";
}

export class MeetingRecorder {
  constructor({ onStateChange, onError, onLevel } = {}) {
    this.onStateChange = onStateChange || (() => {});
    this.onError = onError || (() => {});
    this.onLevel = onLevel || (() => {});
    this.sessionId = crypto.randomUUID();
    this.mimeType = pickMimeType();
    this.mediaRecorder = null;
    this.stream = null;
    this.chunks = [];
    this.startedAt = null;
    this.pausedMs = 0;
    this.pauseStartedAt = null;
    this.analyser = null;
    this.audioContext = null;
    this.rafId = null;
    this.state = "idle";
  }

  _setState(next) {
    this.state = next;
    this.onStateChange(next);
  }

  async start({ source = "mic" } = {}) {
    if (!window.MediaRecorder) {
      this.onError(new Error("This browser does not support MediaRecorder."));
      return;
    }
    if (!this.mimeType) {
      this.onError(new Error("No supported audio MIME type found for recording."));
      return;
    }
    try {
      if (source === "tab") {
        if (!navigator.mediaDevices?.getDisplayMedia) {
          throw new Error("Tab/system audio capture is not supported in this browser.");
        }
        this.stream = await navigator.mediaDevices.getDisplayMedia({
          video: true,
          audio: true,
        });
        // Keep only audio tracks for the recorder; stop video to reduce load.
        for (const track of this.stream.getVideoTracks()) {
          track.stop();
          this.stream.removeTrack(track);
        }
        if (!this.stream.getAudioTracks().length) {
          throw new Error("No tab audio track was shared. Enable audio when prompted.");
        }
      } else {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
      }
    } catch (error) {
      this.onError(error);
      return;
    }

    this.chunks = [];
    this.sessionId = crypto.randomUUID();
    this.startedAt = Date.now();
    this.pausedMs = 0;
    this.pauseStartedAt = null;
    this.mediaRecorder = new MediaRecorder(this.stream, { mimeType: this.mimeType });
    this.mediaRecorder.addEventListener("dataavailable", async (event) => {
      if (!event.data || event.data.size === 0) return;
      this.chunks.push(event.data);
      try {
        await saveChunk(this.sessionId, event.data, this.chunks.length - 1);
      } catch {
        // IndexedDB persistence is best-effort for MVP recovery.
      }
    });
    this.mediaRecorder.start(1000);
    this._startMeter();
    this._setState("recording");
  }

  pause() {
    if (!this.mediaRecorder || this.mediaRecorder.state !== "recording") return;
    this.mediaRecorder.pause();
    this.pauseStartedAt = Date.now();
    this._setState("paused");
  }

  resume() {
    if (!this.mediaRecorder || this.mediaRecorder.state !== "paused") return;
    if (this.pauseStartedAt) {
      this.pausedMs += Date.now() - this.pauseStartedAt;
      this.pauseStartedAt = null;
    }
    this.mediaRecorder.resume();
    this._setState("recording");
  }

  async stop() {
    if (!this.mediaRecorder) return null;
    const recorder = this.mediaRecorder;
    const blobPromise = new Promise((resolve) => {
      recorder.addEventListener(
        "stop",
        () => {
          const type = this.mimeType.split(";")[0] || "audio/webm";
          resolve(new Blob(this.chunks, { type }));
        },
        { once: true },
      );
    });
    recorder.stop();
    this._stopTracks();
    this._stopMeter();
    this._setState("stopped");
    return blobPromise;
  }

  async discard() {
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.stop();
    }
    this._stopTracks();
    this._stopMeter();
    this.chunks = [];
    await clearSession(this.sessionId);
    this._setState("idle");
  }

  elapsedMs() {
    if (!this.startedAt) return 0;
    const pauseExtra =
      this.state === "paused" && this.pauseStartedAt ? Date.now() - this.pauseStartedAt : 0;
    return Date.now() - this.startedAt - this.pausedMs - pauseExtra;
  }

  _stopTracks() {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.mediaRecorder = null;
  }

  _startMeter() {
    if (!this.stream) return;
    this.audioContext = new AudioContext();
    const source = this.audioContext.createMediaStreamSource(this.stream);
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    source.connect(this.analyser);
    const data = new Uint8Array(this.analyser.frequencyBinCount);
    const tick = () => {
      if (!this.analyser) return;
      this.analyser.getByteFrequencyData(data);
      const avg = data.reduce((sum, value) => sum + value, 0) / data.length;
      this.onLevel(avg / 255);
      this.rafId = requestAnimationFrame(tick);
    };
    tick();
  }

  _stopMeter() {
    if (this.rafId) cancelAnimationFrame(this.rafId);
    this.rafId = null;
    this.analyser = null;
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
  }
}

export function extensionForMime(mimeType) {
  if (mimeType.includes("wav")) return "wav";
  if (mimeType.includes("mp4") || mimeType.includes("m4a")) return "m4a";
  if (mimeType.includes("mpeg") || mimeType.includes("mp3")) return "mp3";
  return "webm";
}
