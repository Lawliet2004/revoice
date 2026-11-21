"""Record PCM from the Windows default input using PortAudio."""

import threading

from .speech import BUFFERED_CHUNKS, RATE, Recording, SpeechError


class WindowsRecording(Recording):
    def start(self):
        try:
            import sounddevice
        except (ImportError, OSError) as error:
            raise SpeechError("Couldn’t load the audio driver from the Revoice folder.") from error

        errors = (sounddevice.PortAudioError, ValueError, OSError)
        try:
            stream = self.open_stream(sounddevice, RATE)
        except errors:
            try:
                rate = round(sounddevice.query_devices(kind="input")["default_samplerate"])
                if rate == RATE or rate <= 0:
                    raise
                # The portable Windows runtime bundles Python 3.12 and audioop.
                from audioop import ratecv

                stream = self.open_stream(sounddevice, rate, ratecv)
            except (*errors, ImportError) as error:
                raise SpeechError("Couldn’t open the default microphone. Check Windows microphone access and your input device.") from error

        self.confirm()
        threading.Thread(target=self.finish_capture, args=(sounddevice, stream), daemon=True).start()

    def open_stream(self, sounddevice, rate, ratecv=None):
        conversion_state = None

        def capture(data, _frames, _when, status):
            nonlocal conversion_state
            if self.stopping.is_set():
                raise sounddevice.CallbackStop
            if status.input_overflow:
                self.capture_error = "The microphone skipped audio. Try another recording."
                raise sounddevice.CallbackAbort
            if self.audio.qsize() >= BUFFERED_CHUNKS:
                self.capture_error = "Transcription couldn’t keep up with the recording."
                raise sounddevice.CallbackAbort
            pcm = bytes(data)
            if ratecv:
                pcm, conversion_state = ratecv(pcm, 2, 1, rate, RATE, conversion_state)
            self.byte_count += len(pcm)
            self.audio.put(pcm)

        stream = sounddevice.RawInputStream(
            samplerate=rate, channels=1, dtype="int16", blocksize=rate // 10, callback=capture,
        )
        try:
            stream.start()
        except (sounddevice.PortAudioError, ValueError, OSError):
            try:
                stream.close()
            except sounddevice.PortAudioError:
                pass
            raise
        return stream

    def finish_capture(self, sounddevice, stream):
        try:
            while not self.stopping.wait(.1):
                if not stream.active:
                    if not self.capture_error:
                        self.capture_error = "The microphone stopped. Check the default input device."
                    break
        except sounddevice.PortAudioError:
            self.capture_error = "The microphone stopped. Check the default input device."
        finally:
            try:
                stream.close()
            except sounddevice.PortAudioError:
                if not self.capture_error:
                    self.capture_error = "The microphone disconnected."
            self.audio.put(None)

    def stop(self):
        self.stopping.set()
