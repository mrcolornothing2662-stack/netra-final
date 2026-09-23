/**
 * CyberDrishti AI / NETRA V5 — Connectivity Monitor & Field Mode Simulator
 * Tracks real browser connectivity status and provides manual offline toggle
 * for tactical field rehearsal and conflict resolution simulation.
 */

type ConnectivityListener = (isOnline: boolean) => void;

class ConnectivityManager {
  private listeners: Set<ConnectivityListener> = new Set();
  private simulatedOffline: boolean = false;

  constructor() {
    if (typeof window !== 'undefined') {
      window.addEventListener('online', () => this.notify());
      window.addEventListener('offline', () => this.notify());
    }
  }

  public isOnline(): boolean {
    if (this.simulatedOffline) return false;
    return typeof window !== 'undefined' ? window.navigator.onLine : true;
  }

  public isSimulatedOffline(): boolean {
    return this.simulatedOffline;
  }

  public setSimulatedOffline(offline: boolean): void {
    this.simulatedOffline = offline;
    this.notify();
  }

  public subscribe(listener: ConnectivityListener): () => void {
    this.listeners.add(listener);
    listener(this.isOnline());
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    const status = this.isOnline();
    this.listeners.forEach((listener) => {
      try {
        listener(status);
      } catch (err) {
        console.error('[Connectivity] Error in listener callback:', err);
      }
    });
  }
}

export const connectivity = new ConnectivityManager();
