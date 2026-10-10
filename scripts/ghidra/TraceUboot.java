// Headless post-script: verify base-address mapping, decompile do_boot_android,
// walk its call graph looking for MMC/block-write functions, resolve known
// string-adjacent function addresses via cross references.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.Reference;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class TraceUboot extends GhidraScript {

    DecompInterface decomp;
    Set<Long> visited = new HashSet<>();
    static final long DO_BOOT_ANDROID_VA = 0x208774L;
    static final long DISPATCH_VA = 0x2298a0L;

    @Override
    public void run() throws Exception {
        decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        decomp.setSimplificationStyle("decompile");

        println("=========================================================");
        println("STEP 1: verify base address mapping");
        println("=========================================================");
        verifyBaseAddress();

        println("\n=========================================================");
        println("STEP 2: resolve known strings -> containing functions");
        println("=========================================================");
        String[] strs = {
            "boot_android", "android_image_load_by_partname", "android_bcb_write",
            "android_get_dtbo", "gpt_restore", "gpt_verify_headers", "is_valid_gpt_buf",
            "write_mbr_and_gpt_partitions", "set_protective_mbr", "fb_mmc_flash_write",
            "blk_dwrite", "mmc write", "mmc erase", "system", "super"
        };
        for (String s : strs) {
            resolveStringFunction(s);
        }

        println("\n=========================================================");
        println("STEP 3: decompile do_boot_android");
        println("=========================================================");
        Function doBoot = getOrMakeFunction(DO_BOOT_ANDROID_VA, "do_boot_android");
        printFull(doBoot);

        println("\n=========================================================");
        println("STEP 4: list direct callees of do_boot_android");
        println("=========================================================");
        List<Function> callees = listCallees(doBoot);
        for (Function c : callees) {
            println("  callee: " + c.getName() + " @ " + c.getEntryPoint());
        }

        println("\n=========================================================");
        println("STEP 5: decompile dispatch function @ file 0x2a0a0");
        println("=========================================================");
        Function dispatch = getOrMakeFunction(DISPATCH_VA, "dispatch_boot_img_hdr");
        printFull(dispatch);

        println("\n=========================================================");
        println("STEP 6: walk call graph from do_boot_android, depth<=3,");
        println("full-print any function whose decompiled body mentions a write/mmc/blk/gpt keyword");
        println("=========================================================");
        visited.clear();
        walk(doBoot, 0, 3);
    }

    void verifyBaseAddress() throws Exception {
        Address strAddr = findAsciiString("boot_android");
        if (strAddr == null) {
            println("  !! could not find 'boot_android' string in memory");
            return;
        }
        println("  'boot_android' string @ " + strAddr);
        byte[] ptrBytes = longToLE(DO_BOOT_ANDROID_VA);
        Memory mem = currentProgram.getMemory();
        Address hit = mem.findBytes(currentProgram.getMinAddress(), ptrBytes, null, true, monitor);
        boolean confirmed = false;
        while (hit != null) {
            long lo = strAddr.getOffset() - 0x40;
            long hi = strAddr.getOffset() + 0x40;
            if (hit.getOffset() >= lo && hit.getOffset() <= hi) {
                println("  CONFIRMED: pointer to do_boot_android (0x" + Long.toHexString(DO_BOOT_ANDROID_VA)
                        + ") found @ " + hit + ", within 0x40 bytes of 'boot_android' string -> cmd_tbl entry, base mapping validated.");
                confirmed = true;
                break;
            }
            hit = mem.findBytes(hit.next(), ptrBytes, null, true, monitor);
        }
        if (!confirmed) {
            println("  WARNING: no pointer to 0x" + Long.toHexString(DO_BOOT_ANDROID_VA)
                    + " found near the 'boot_android' string. Base address mapping NOT independently confirmed by this method.");
        }
    }

    void resolveStringFunction(String s) throws Exception {
        Address a = findAsciiString(s);
        if (a == null) {
            println("  \"" + s + "\": not found");
            return;
        }
        println("  \"" + s + "\" string @ " + a);
        for (Reference ref : getReferencesTo(a)) {
            Address from = ref.getFromAddress();
            Function f = getFunctionContaining(from);
            if (f != null) {
                println("      referenced from " + from + " inside function " + f.getName() + " @ " + f.getEntryPoint());
            } else {
                println("      referenced from " + from + " (not inside a known function)");
            }
        }
    }

    Address findAsciiString(String s) throws Exception {
        byte[] pat = s.getBytes(StandardCharsets.US_ASCII);
        Memory mem = currentProgram.getMemory();
        return mem.findBytes(currentProgram.getMinAddress(), pat, null, true, monitor);
    }

    byte[] longToLE(long v) {
        byte[] b = new byte[8];
        for (int i = 0; i < 8; i++) {
            b[i] = (byte) ((v >> (8 * i)) & 0xff);
        }
        return b;
    }

    Function getOrMakeFunction(long va, String name) throws Exception {
        Address addr = toAddr(va);
        Function f = getFunctionAt(addr);
        if (f == null) {
            try {
                disassemble(addr);
            } catch (Exception e) {
                println("  disassemble() failed at " + addr + ": " + e);
            }
            f = createFunction(addr, name);
            if (f != null) {
                analyzeChanges(currentProgram);
            }
        }
        if (f == null) {
            println("  !! FAILED to obtain function at " + addr);
        } else {
            println("  function @ " + addr + " -> " + f.getName());
        }
        return f;
    }

    void printFull(Function f) throws Exception {
        if (f == null) {
            println("  <null function, skipped>");
            return;
        }
        println("--- " + f.getName() + " @ " + f.getEntryPoint() + " ---");
        DecompileResults res = decomp.decompileFunction(f, 90, monitor);
        if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) {
            println(res.getDecompiledFunction().getC());
        } else {
            println("  <decompile failed: " + (res != null ? res.getErrorMessage() : "null result") + ">");
        }
    }

    List<Function> listCallees(Function f) {
        List<Function> out = new ArrayList<>();
        if (f == null) return out;
        for (Function c : f.getCalledFunctions(monitor)) {
            out.add(c);
        }
        return out;
    }

    static final String[] KEYWORDS = {
        "write", "mmc", "blk_d", "block_dev", "sector", " lba", "erase(", "->write", "ops->"
    };

    void walk(Function f, int depth, int maxDepth) throws Exception {
        if (f == null) return;
        long key = f.getEntryPoint().getOffset();
        if (visited.contains(key)) return;
        visited.add(key);

        DecompileResults res = decomp.decompileFunction(f, 60, monitor);
        String code = (res != null && res.getDecompiledFunction() != null) ? res.getDecompiledFunction().getC() : "";
        String lower = code.toLowerCase();
        boolean interesting = false;
        for (String k : KEYWORDS) {
            if (lower.contains(k)) { interesting = true; break; }
        }
        println((interesting ? "[MATCH] " : "[skip ] ") + f.getName() + " @ " + f.getEntryPoint()
                + " depth=" + depth + " size=" + f.getBody().getNumAddresses());
        if (interesting) {
            println(code);
        }
        if (depth >= maxDepth) return;
        for (Function c : f.getCalledFunctions(monitor)) {
            walk(c, depth + 1, maxDepth);
        }
    }
}
