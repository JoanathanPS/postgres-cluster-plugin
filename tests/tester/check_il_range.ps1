. .\tester\il_disasm.ps1
$dc = $asm.GetType('Site24x7PluginAgent.DataCollection')
$m = $dc.GetMethod('RunPluginandWriteToRegFile', [System.Reflection.BindingFlags]'Public,NonPublic,Static,Instance')

Add-Type -TypeDefinition @"
using System;
using System.Reflection;
using System.Reflection.Emit;

public class RangeDisasm {
    public static void ShowRange(MethodInfo method, int start, int end) {
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
                    if (oc.Size == 2 && (ushort)oc.Value == (ushort)((0xfe << 8) | b2)) {
                        op = oc; break;
                    }
                }
            } else {
                op = OpCodes.Nop;
                foreach (FieldInfo fi in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)) {
                    OpCode oc = (OpCode)fi.GetValue(null);
                    if (oc.Size == 1 && (byte)oc.Value == b) {
                        op = oc; break;
                    }
                }
            }
            string operandStr = "";
            switch (op.OperandType) {
                case OperandType.InlineString:
                    int tok = BitConverter.ToInt32(il, pos); pos += 4;
                    try { operandStr = "\"" + module.ResolveString(tok) + "\""; } catch {}
                    break;
                case OperandType.InlineMethod:
                case OperandType.InlineField:
                case OperandType.InlineType:
                case OperandType.InlineTok:
                    int mTok = BitConverter.ToInt32(il, pos); pos += 4;
                    try { MemberInfo mi = module.ResolveMember(mTok); operandStr = mi.DeclaringType.Name + "." + mi.Name; } catch {}
                    break;
                case OperandType.InlineI:
                case OperandType.InlineBrTarget:
                    operandStr = BitConverter.ToInt32(il, pos).ToString(); pos += 4;
                    break;
                case OperandType.ShortInlineI:
                case OperandType.ShortInlineVar:
                    operandStr = il[pos++].ToString();
                    break;
                case OperandType.ShortInlineBrTarget:
                    sbyte bVal = (sbyte)il[pos++];
                    operandStr = (offset + 2 + bVal).ToString("X4");
                    break;
                case OperandType.InlineVar:
                    operandStr = BitConverter.ToInt16(il, pos).ToString(); pos += 2;
                    break;
                default:
                    break;
            }
            if (offset >= start && offset <= end) {
                Console.WriteLine(string.Format("IL_{0:X4}: {1} {2}", offset, op.Name, operandStr));
            }
        }
    }
}
"@

[RangeDisasm]::ShowRange($m, 0x0540, 0x0615)
