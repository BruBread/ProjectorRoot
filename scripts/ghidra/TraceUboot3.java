// Quick look at boot_fit / bootrkp command handlers: locate via string xref,
// decompile the handler, and one level of callees, flag write/mmc/blk keywords.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.Reference;
import java.nio.charset.StandardCharsets;

public class TraceUboot3 extends GhidraScript {
    DecompInterface decomp;

    @Override
    public void run() throws Exception {
        decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        decomp.setSimplificationStyle("decompile");

        for (String cmd : new String[]{"boot_fit", "bootrkp"}) {
            println("\n############ command string: " + cmd + " ############");
            Address strAddr = findAscii(cmd);
            if (strAddr == null) { println("  string not found"); continue; }
            println("  string @ " + strAddr);
            for (Reference ref : getReferencesTo(strAddr)) {
                Address from = ref.getFromAddress();
                Function f = getFunctionContaining(from);
                println("  string referenced from " + from + (f != null ? " in " + f.getName() : " (no function)"));
            }
        }
    }

    Address findAscii(String s) throws Exception {
        byte[] pat = s.getBytes(StandardCharsets.US_ASCII);
        Memory mem = currentProgram.getMemory();
        return mem.findBytes(currentProgram.getMinAddress(), pat, null, true, monitor);
    }
}
