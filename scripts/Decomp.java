// Decompile functions at given addresses (args: outfile addr1 addr2 ...)
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.Function;
import java.io.*;
public class Decomp extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    PrintWriter w = new PrintWriter(new FileWriter(a[0]));
    DecompInterface d = new DecompInterface(); d.openProgram(currentProgram);
    for (int i=1;i<a.length;i++) {
      long v = Long.parseLong(a[i].replace("0x",""),16) & ~1L;
      var ad = toAddr(v);
      Function f = getFunctionContaining(ad);
      if (f==null) { disassemble(ad); f = createFunction(ad,null); }
      if (f==null) { w.println("// no function at "+a[i]); continue; }
      var r = d.decompileFunction(f, 120, monitor);
      w.println("// ===== "+f.getName()+" @ "+f.getEntryPoint());
      w.println(r.decompileCompleted()? r.getDecompiledFunction().getC() : "// decompile failed");
    }
    w.close();
  }
}
