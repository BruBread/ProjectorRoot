// Compile-time stub: only the signatures ProjMap uses. The real class comes from the device's framework.
package android.view;
public class SurfaceControl {
    public static class Builder {
        public Builder() { throw new RuntimeException(); }
        public Builder setName(String name) { throw new RuntimeException(); }
        public Builder setBufferSize(int w, int h) { throw new RuntimeException(); }
        public Builder setFormat(int format) { throw new RuntimeException(); }
        public SurfaceControl build() { throw new RuntimeException(); }
    }
    public static class Transaction {
        public Transaction() { throw new RuntimeException(); }
        public Transaction setLayer(SurfaceControl sc, int z) { throw new RuntimeException(); }
        public Transaction setVisibility(SurfaceControl sc, boolean visible) { throw new RuntimeException(); }
        public void apply() { throw new RuntimeException(); }
    }
}
