// Import CHDK funcs_by_name.csv (addr,name) as function labels; thumb addrs have bit0 set.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.listing.Function;
import java.io.*;
public class ImportChdkLabels extends GhidraScript {
  public void run() throws Exception {
    String path = getScriptArgs()[0];
    BufferedReader r = new BufferedReader(new FileReader(path));
    String line; int n=0;
    while ((line = r.readLine()) != null) {
      String[] p = line.trim().split(",");
      if (p.length < 2 || !p[0].startsWith("0x")) continue;
      long v = Long.parseLong(p[0].substring(2),16) & ~1L;
      Address a = toAddr(v);
      if (currentProgram.getMemory().getBlock(a)==null) continue;
      try {
        if ((Long.parseLong(p[0].substring(2),16)&1)==1) {
          setRegisterValue(a, "TMode", 1);
        }
        createLabel(a, p[1].replaceAll("[^A-Za-z0-9_.]","_"), true, SourceType.IMPORTED);
        disassemble(a);
        if (getFunctionAt(a)==null) createFunction(a, null);
        n++;
      } catch (Exception e) {}
    }
    println("imported "+n);
  }
  void setRegisterValue(Address a, String reg, int val) throws Exception {
    var ctx = currentProgram.getProgramContext();
    ctx.setValue(ctx.getRegister(reg), a, a, java.math.BigInteger.valueOf(val));
  }
}
