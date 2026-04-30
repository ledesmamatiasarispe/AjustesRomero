using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;

namespace Microsoft.Office.Interop.Excel;

[ComImport]
[CompilerGenerated]
[Guid("000208D8-0000-0000-C000-000000000046")]
[TypeIdentifier]
public interface _Worksheet
{
	[DispId(238)]
	Range Cells
	{
		[MethodImpl(MethodImplOptions.InternalCall)]
		[DispId(238)]
		[return: MarshalAs(UnmanagedType.Interface)]
		get;
	}

	[DispId(197)]
	Range Range
	{
		[MethodImpl(MethodImplOptions.InternalCall)]
		[DispId(197)]
		[return: MarshalAs(UnmanagedType.Interface)]
		get;
	}

	void _VtblGap1_45();

	void _VtblGap2_47();
}
