// A write that waits for the changes to settle.
//
// A control that fires on every change — a select, a slider drag — would
// otherwise write on every step. The writer holds the newest value and
// writes it once the user stops changing things.
//
// The timers are injectable, so the behaviour can be tested without
// waiting for real time to pass.

/**
 * A writer that saves the last value it was given, after a delay.
 *
 * @param {Function} write   Called with the value to save.
 * @param {number} delay     How long to wait, in milliseconds.
 * @param {Object} timers    Optional { setTimeout, clearTimeout }.
 */
export function createDebouncedWriter(write, delay, timers = {}) {
  const schedule = timers.setTimeout || setTimeout;
  const cancel = timers.clearTimeout || clearTimeout;

  let timer = null;
  let pending = null;

  const writePending = () => {
    const value = pending;
    pending = null;
    if (value !== null && value !== undefined) write(value);
  };

  return {
    /**
     * Record a new value. Any write that was waiting is replaced by it.
     */
    schedule(value) {
      pending = value;
      if (timer !== null) cancel(timer);
      timer = schedule(() => {
        timer = null;
        writePending();
      }, delay);
    },

    /**
     * Write anything still waiting, straight away.
     *
     * This is what runs when the app goes away: a change the user made
     * a moment before is not lost.
     */
    flush() {
      if (timer !== null) {
        cancel(timer);
        timer = null;
      }
      writePending();
    },

    /** Whether a write is waiting to happen. */
    get hasPending() {
      return pending !== null && pending !== undefined;
    },
  };
}
