import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffXfermode;
import android.os.IBinder;
import android.os.Parcel;
import android.view.Surface;
import android.view.SurfaceControl;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Method;

/**
 * Projection-mapping helper, run on the projector as root:
 *   CLASSPATH=/data/local/tmp/projmap.dex app_process / ProjMap <width> <height>
 * Owns full-screen layers above everything (the mask, and the alignment grid just below it) and sets
 * properties in-process, which skips the ~30-50ms process spawn a shell `setprop` costs on this SoC.
 * One command per stdin line, one "ok" / "err <why>" reply per line:
 *   mask x1 y1 x2 y2 x3 y3 ...   black everywhere outside this polygon (layer pixels)
 *   mask off                     no mask
 *   grid on|off                  alignment grid over everything but the mask
 *   prop NAME VALUE              android.os.SystemProperties.set
 *   redraw                       make SurfaceFlinger really draw a frame (see keystone.py apply())
 * The layers go away when this process exits.
 */
public class ProjMap {
    static int w, h;
    static SurfaceControl layer, grid;
    static Surface surface;
    static IBinder flinger;
    static Method setProp;
    static boolean dim;

    public static void main(String[] args) throws Exception {
        w = Integer.parseInt(args[0]);
        h = Integer.parseInt(args[1]);
        layer = newLayer("projmap-mask", Integer.MAX_VALUE);
        surface = new Surface(layer);
        flinger = (IBinder) Class.forName("android.os.ServiceManager")
                .getMethod("getService", String.class).invoke(null, "SurfaceFlinger");
        setProp = Class.forName("android.os.SystemProperties").getMethod("set", String.class, String.class);

        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        reply("ready");
        for (String line; (line = in.readLine()) != null; ) {
            try {
                run(line.trim().split("\\s+"));
                reply("ok");
            } catch (Exception e) {
                Throwable c = e.getCause() != null ? e.getCause() : e;
                reply("err " + c.toString().replace('\n', ' '));
            }
        }
        if (dim) redraw();  // PC side closed: leave saturation at 1.0
    }

    /** A hidden full-screen layer at height z. */
    static SurfaceControl newLayer(String name, int z) throws Exception {
        SurfaceControl l = new SurfaceControl.Builder().setName(name)
                .setBufferSize(w, h).setFormat(-3 /* PixelFormat.TRANSLUCENT */).build();
        SurfaceControl.Transaction t = new SurfaceControl.Transaction();
        // A parentless layer only shows once it is on the display's layer stack (hidden API).
        t.getClass().getMethod("setLayerStack", SurfaceControl.class, int.class).invoke(t, l, 0);
        t.setLayer(l, z).setVisibility(l, false).apply();
        return l;
    }

    static void reply(String s) {
        System.out.println(s);
        System.out.flush();
    }

    static void run(String[] c) throws Exception {
        switch (c[0]) {
            case "mask":
                if (c.length == 2 && c[1].equals("off")) {
                    new SurfaceControl.Transaction().setVisibility(layer, false).apply();  // hidden: no blending cost
                    return;
                }
                if (c.length < 7 || c.length % 2 == 0) throw new IllegalArgumentException("mask needs 3+ x y pairs");
                float[] p = new float[c.length - 1];
                for (int i = 0; i < p.length; i++) p[i] = Float.parseFloat(c[i + 1]);
                draw(p);
                new SurfaceControl.Transaction().setVisibility(layer, true).apply();
                return;
            case "grid":
                if (grid == null) {
                    grid = newLayer("projmap-grid", Integer.MAX_VALUE - 1);  // below the mask, so the mask still shows
                    drawGrid(new Surface(grid));
                }
                new SurfaceControl.Transaction().setVisibility(grid, c[1].equals("on")).apply();
                return;
            case "prop":
                setProp.invoke(null, c[1], c[2]);
                return;
            case "redraw":
                redraw();
                return;
            default:
                throw new IllegalArgumentException("unknown command " + c[0]);
        }
    }

    static void draw(float[] poly) {
        Canvas c = surface.lockCanvas(null);
        c.drawColor(0xFF000000, PorterDuff.Mode.SRC);
        Path hole = new Path();
        hole.moveTo(poly[0], poly[1]);
        for (int i = 2; i < poly.length; i += 2) hole.lineTo(poly[i], poly[i + 1]);
        hole.close();
        Paint clear = new Paint();
        clear.setAntiAlias(true);
        clear.setXfermode(new PorterDuffXfermode(PorterDuff.Mode.CLEAR));
        c.drawPath(hole, clear);
        surface.unlockCanvasAndPost(c);
    }

    /** White 80px grid on black, corner squares colored like the page's handles (lt red, rt green, lb blue, rb yellow). */
    static void drawGrid(Surface s) {
        Canvas c = s.lockCanvas(null);
        c.drawColor(0xFF000000, PorterDuff.Mode.SRC);
        Paint p = new Paint();
        p.setColor(0xFFFFFFFF);
        for (int x = 0; x < w; x += 80) c.drawRect(x, 0, x + 3, h, p);
        for (int y = 0; y < h; y += 80) c.drawRect(0, y, w, y + 3, p);
        c.drawRect(w - 3, 0, w, h, p);
        c.drawRect(0, h - 3, w, h, p);
        int[] colors = {0xFFFF3C3C, 0xFF3CDC3C, 0xFF3C8CFF, 0xFFFFD23C};
        for (int i = 0; i < 4; i++) {
            p.setColor(colors[i]);
            float x = i % 2 * (w - 40), y = i / 2 * (h - 40);
            c.drawRect(x, y, x + 40, y + 40, p);
        }
        s.unlockCanvasAndPost(c);
    }

    /** SurfaceFlinger transaction 1022 = global saturation. Alternating 1.0/0.999 changes every frame,
     *  which defeats the client-composition cache so RenderEngine re-reads the keystone props. */
    static void redraw() throws Exception {
        Parcel data = Parcel.obtain();
        data.writeInterfaceToken("android.ui.ISurfaceComposer");
        data.writeFloat((dim = !dim) ? 0.999f : 1f);
        flinger.transact(1022, data, null, 0);
        data.recycle();
    }
}
