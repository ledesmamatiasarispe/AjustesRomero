using System;
using System.Windows.Forms;
using CarbomaxDelta.Data;

namespace CarbomaxDelta;

internal static class Program
{
	public static string dbFile = Application.StartupPath + "\\dados.db";

	[STAThread]
	private static void Main()
	{
		try
		{
			DbUtils.CheckDbExistAndCreate();
			Application.EnableVisualStyles();
			Application.SetCompatibleTextRenderingDefault(defaultValue: false);
			Application.Run(new frmMain());
		}
		catch (Exception ex)
		{
			MessageBox.Show(ex.Message);
		}
	}
}
