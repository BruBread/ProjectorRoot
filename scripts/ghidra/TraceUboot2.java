// Second pass: decompile the specific callees identified from do_boot_android's
// pseudocode (FUN_0023d9fc, FUN_0023dcdc, FUN_002237f8, FUN_00223774) and one
// level of their own callees, flagging anything write/mmc/blk-ish.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.util.*;

public class TraceUboot2 extends GhidraScript {
    DecompInterface decomp;

    @Override
    public void run() throws Exception {
        decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        decomp.setSimplificationStyle("decompile");

        long[] targets = { 0x23d9fcL, 0x23dcdcL, 0x2237f8L, 0x223774L, 0x233bcL + 0x220000L };
        // note: 0x233bc is a *file offset* fragment from notes; real address for
        // android_get_dtbo referencer already known as 0x2233bc, included directly below instead.
        long[] realTargets = { 0x23d9fcL, 0x23dcdcL, 0x2237f8L, 0x223774L, 0x2233bcL };

        for (long va : realTargets) {
            Address a = toAddr(va);
            Function f = getFunctionAt(a);
            println("\n================ " + a + " ================");
            if (f == null) {
                println("  no function object here (address may be mid-function); trying containing function");
                f = getFunctionContaining(a);
            }
            if (f == null) {
                println("  still null, skipping");
                continue;
            }
            printFull(f);
            println("  -- callees of " + f.getName() + " --");
            for (Function c : f.getCalledFunctions(monitor)) {
                println("     " + c.getName() + " @ " + c.getEntryPoint());
            }
        }
    }

    void printFull(Function f) throws Exception {
        println("--- " + f.getName() + " @ " + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses() + " ---");
        DecompileResults res = decomp.decompileFunction(f, 90, monitor);
        if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) {
            println(res.getDecompiledFunction().getC());
        } else {
            println("  <decompile failed: " + (res != null ? res.getErrorMessage() : "null result") + ">");
        }
    }
}
