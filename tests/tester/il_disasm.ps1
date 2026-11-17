Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
using System.Reflection.Emit;
using System.Collections.Generic;

public class ILDisassembler {
    public static void Disassemble(MethodInfo method) {
        if (method == null) return;
        Console.WriteLine("METHOD: " + method.DeclaringType.FullName + "." + method.Name);
        MethodBody body = method.GetMethodBody();
        if (body == null) {
            Console.WriteLine("No body");
            return;
        }
        byte[] il = body.GetILAsByteArray();
        Module module = method.Module;
        int pos = 0;
        while (pos < il.Length) {
            int offset = pos;
            byte b = il[pos++];
            OpCode op;
            if (b == 0xfe) {
                byte b2 = il[pos++];
                op = (OpCode)typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)[0].GetValue(null); // fallback
                // find 2-byte opcode
                foreach (FieldInfo fi in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)) {
                    OpCode oc = (OpCode)fi.GetValue(null);
                    if (oc.Size == 2 && (ushort)oc.Value == (ushort)((0xfe << 8) | b2)) {
                        op = oc;
                        break;
                    }
                }
            } else {
                op = (OpCode)typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)[0].GetValue(null);
                foreach (FieldInfo fi in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)) {
                    OpCode oc = (OpCode)fi.GetValue(null);
                    if (oc.Size == 1 && (byte)oc.Value == b) {
                        op = oc;
                        break;
                    }
                }
            }

            string operandStr = "";
            switch (op.OperandType) {
                case OperandType.InlineString:
                    int tok = BitConverter.ToInt32(il, pos);
                    pos += 4;
                    try {
                        operandStr = "\"" + module.ResolveString(tok) + "\"";
                    } catch { operandStr = "token:" + tok; }
                    break;
                case OperandType.InlineMethod:
                case OperandType.InlineField:
                case OperandType.InlineType:
                case OperandType.InlineTok:
                    int mTok = BitConverter.ToInt32(il, pos);
                    pos += 4;
                    try {
                        MemberInfo mi = module.ResolveMember(mTok);
                        operandStr = mi.DeclaringType.Name + "." + mi.Name;
                    } catch { operandStr = "token:" + mTok; }
                    break;
                case OperandType.InlineI:
                case OperandType.InlineBrTarget:
                    int val = BitConverter.ToInt32(il, pos);
                    pos += 4;
                    operandStr = val.ToString();
                    break;
                case OperandType.ShortInlineI:
                case OperandType.ShortInlineVar:
                    operandStr = il[pos++].ToString();
                    break;
                case OperandType.ShortInlineBrTarget:
                    sbyte bVal = (sbyte)il[pos++];
                    operandStr = (offset + 1 + 1 + bVal).ToString();
                    break;
                case OperandType.InlineVar:
                    operandStr = BitConverter.ToInt16(il, pos).ToString();
                    pos += 2;
                    break;
                case OperandType.InlineNone:
                    break;
                default:
                    // skip appropriate bytes
                    break;
            }
            if (operandStr.Length > 0)
                Console.WriteLine(string.Format("  IL_{0:X4}: {1} {2}", offset, op.Name, operandStr));
            else
                Console.WriteLine(string.Format("  IL_{0:X4}: {1}", offset, op.Name));
        }
    }
}
"@

$path = 'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\bin\Pluginbin\x64\Site24x7PluginAgent.exe'
$bytes = [System.IO.File]::ReadAllBytes($path)
$asm = [System.Reflection.Assembly]::Load($bytes)
# done

