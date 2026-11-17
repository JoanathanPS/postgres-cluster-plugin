. .\tester\il_disasm.ps1
$dc = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $dc.GetMethod('RunPluginandWriteToFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

Add-Type -TypeDefinition @"
using System;
using System.Reflection;
using System.Reflection.Emit;

public class RangeDisasm2 {
    public static void ShowStrings(MethodInfo method) {
        MethodBody body = method.GetMethodBody();
        byte[] il = body.GetILAsByteArray();
        Module module = method.Module;
        int pos = 0;
        while (pos < il.Length) {
            int offset = pos;
            byte b = il[pos++];
            OpCode op;
            if (b == 0xfe) {
                byte b2 = il[pos++];
                op = OpCodes.Nop;
                foreach (FieldInfo fi in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)) {
                    OpCode oc = (OpCode)fi.GetValue(null);
                    if (oc.Size == 2 && (ushort)oc.Value == (ushort)((0xfe << 8) | b2)) { op = oc; break; }
                }
            } else {
                op = OpCodes.Nop;
                foreach (FieldInfo fi in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)) {
                    OpCode oc = (OpCode)fi.GetValue(null);
                    if (oc.Size == 1 && (byte)oc.Value == b) { op = oc; break; }
                }
            }
            if (op.OperandType == OperandType.InlineString) {
                int tok = BitConverter.ToInt32(il, pos); pos += 4;
                try { Console.WriteLine("IL_" + offset.ToString("X4") + ": \"" + module.ResolveString(tok) + "\""); } catch {}
            } else {
                switch (op.OperandType) {
                    case OperandType.InlineMethod:
                    case OperandType.InlineField:
                    case OperandType.InlineType:
                    case OperandType.InlineTok:
                    case OperandType.InlineI:
                    case OperandType.InlineBrTarget:
                        pos += 4; break;
                    case OperandType.ShortInlineI:
                    case OperandType.ShortInlineVar:
                    case OperandType.ShortInlineBrTarget:
                        pos += 1; break;
                    case OperandType.InlineVar:
                        pos += 2; break;
                }
            }
        }
    }
}
"@

[RangeDisasm2]::ShowStrings($m)
