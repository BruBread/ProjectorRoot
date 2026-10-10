// Trace do_bootrkp (found via structural cmd_tbl scan, VA 0x208ab0) and
// do_boot_fit is NOT registered as a real command (absent from cmd table --
// noted for the record, not traced further). Walk bootrkp's call graph,
// flag write/mmc/blk/gpt/lba/sector/erase keywords, and check whether any
// of the 7 previously-identified "smoking gun" functions are reached.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.util.*;

public class TraceBootrkp extends GhidraScript {

    DecompInterface decomp;
    Set<Long> visited = new HashSet<>();
    static final long DO_BOOTRKP_VA = 0x208ab0L;

    // previously-resolved "smoking gun" candidates from do_boot_android pass
    static final Map<Long, String> SMOKING_GUNS = new HashMap<>();
    static {
        SMOKING_GUNS.put(0x226d54L, "fb_mmc_flash_write");
        SMOKING_GUNS.put(0x22c920L, "gpt_restore");
        SMOKING_GUNS.put(0x22ce00L, "write_mbr_and_gpt_partitions");
        SMOKING_GUNS.put(0x222e68L, "android_bcb_write");
        SMOKING_GUNS.put(0x22ca70L, "gpt_verify_headers");
        SMOKING_GUNS.put(0x22ccfcL, "is_valid_gpt_buf");
        SMOKING_GUNS.put(0x22af98L, "set_protective_mbr");
    }

    static final String[] KEYWORDS = {
        "write", "mmc", "blk_d", "block_dev", "sector", " lba", "erase(", "->write", "ops->", "gpt"
    };

    @Override
    public void run() throws Exception {
        decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        decomp.setSimplificationStyle("decompile");

        println("=========================================================");
        println("do_bootrkp @ VA 0x" + Long.toHexString(DO_BOOTRKP_VA));
        println("=========================================================");
        Function doBootrkp = getOrMakeFunction(DO_BOOTRKP_VA, "do_bootrkp");
        printFull(doBootrkp);

        println("\n=========================================================");
        println("Full call graph walk, depth<=5, flagging keyword hits and smoking-gun hits");
        println("=========================================================");
        visited.clear();
        walk(doBootrkp, 0, 5);

        println("\n=========================================================");
        println("SUMMARY: smoking-gun functions reached from do_bootrkp:");
        println("=========================================================");
        boolean any = false;
        for (Map.Entry<Long, String> e : SMOKING_GUNS.entrySet()) {
            if (visited.contains(e.getKey())) {
                println("  REACHED: " + e.getValue() + " @ 0x" + Long.toHexString(e.getKey()));
                any = true;
            }
        }
        if (!any) {
            println("  none of the 7 smoking-gun functions were reached within depth 5");
        }
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
        boolean isGun = SMOKING_GUNS.containsKey(key);
        println((isGun ? "[GUN!] " : (interesting ? "[MATCH] " : "[skip ] ")) + f.getName() + " @ " + f.getEntryPoint()
                + " depth=" + depth + " size=" + f.getBody().getNumAddresses());
        if (interesting || isGun) {
            println(code);
        }
        if (depth >= maxDepth) return;
        for (Function c : f.getCalledFunctions(monitor)) {
            walk(c, depth + 1, maxDepth);
        }
    }
}
