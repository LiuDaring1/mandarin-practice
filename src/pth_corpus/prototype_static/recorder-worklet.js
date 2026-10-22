class ReadingRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.recording = false;
    this.port.onmessage = ({data}) => {
      this.recording = data === 'start';
      if (data === 'stop') this.port.postMessage({done: true});
    };
  }
  process(inputs) {
    if (this.recording && inputs[0]?.[0]) {
      const input = inputs[0];
      const mono = new Float32Array(input[0].length);
      input.forEach(channel => channel.forEach((value, i) => { mono[i] += value / input.length; }));
      this.port.postMessage({samples: mono}, [mono.buffer]);
    }
    return true;
  }
}
registerProcessor('reading-recorder', ReadingRecorder);
