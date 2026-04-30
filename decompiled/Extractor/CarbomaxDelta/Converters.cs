using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Data;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Office.Interop.Excel;

namespace CarbomaxDelta;

public static class Converters
{
	public static IList<T> Clone<T>(this IList<T> listToClone) where T : ICloneable
	{
		return listToClone.Select((T item) => (T)item.Clone()).ToList();
	}

	public static double ConvertCelsiusToFahrenheit(int unit, double c)
	{
		if (unit == 0)
		{
			return c;
		}
		return c * 1.8 + 32.0;
	}

	public static double ConvertFahrenheitToCelsius(double f)
	{
		return 1.8 * (f - 32.0);
	}

	public static void SaveDataGridViewToXLS(DataGridView grid1)
	{
		try
		{
			Microsoft.Office.Interop.Excel.Application application = (Microsoft.Office.Interop.Excel.Application)Activator.CreateInstance(Marshal.GetTypeFromCLSID(new Guid("00024500-0000-0000-C000-000000000046")));
			application.Visible = false;
			_Workbook workbook = application.Workbooks.Add(Missing.Value);
			_Worksheet worksheet = (_Worksheet)(dynamic)workbook.ActiveSheet;
			int num = 0;
			for (int i = 2; i < grid1.ColumnCount; i++)
			{
				if (grid1.Columns[i].Visible)
				{
					worksheet.Cells[1, ++num] = grid1.Columns[i].HeaderText;
				}
			}
			worksheet.get_Range((object)"A1", (object)"T1").Font.Bold = true;
			for (int j = 0; j < grid1.RowCount; j++)
			{
				num = 0;
				for (int k = 2; k < grid1.ColumnCount; k++)
				{
					if (grid1.Rows[j].Cells[k].Visible)
					{
						worksheet.Cells[j + 2, ++num] = grid1.Rows[j].Cells[k].Value;
					}
				}
			}
			worksheet.Cells.Select();
			worksheet.Cells.EntireColumn.AutoFit();
			((dynamic)worksheet.Cells[1, 1]).Select();
			application.Visible = true;
		}
		catch (Exception ex)
		{
			MessageBox.Show(string.Concat(string.Concat("Error: " + ex.Message, " Line: "), ex.Source), "Error");
		}
	}

	public static void SaveDataRowGridViewToXLS(DataGridView grid1, DataGridView grid2)
	{
		try
		{
			Microsoft.Office.Interop.Excel.Application application = (Microsoft.Office.Interop.Excel.Application)Activator.CreateInstance(Marshal.GetTypeFromCLSID(new Guid("00024500-0000-0000-C000-000000000046")));
			application.Visible = false;
			_Workbook workbook = application.Workbooks.Add(Missing.Value);
			_Worksheet worksheet = (_Worksheet)(dynamic)workbook.ActiveSheet;
			int num = 0;
			for (int i = 2; i < grid1.ColumnCount; i++)
			{
				if (grid1.Columns[i].Visible)
				{
					worksheet.Cells[1, ++num] = grid1.Columns[i].HeaderText;
				}
			}
			worksheet.get_Range((object)"A1", (object)"T1").Font.Bold = true;
			num = 0;
			for (int j = 2; j < grid1.ColumnCount; j++)
			{
				if (grid1.Columns[j].Visible)
				{
					worksheet.Cells[2, ++num] = grid1.Rows[grid1.CurrentRow.Index].Cells[j].Value;
				}
			}
			num = 0;
			for (int k = 1; k < grid2.ColumnCount; k++)
			{
				if (grid2.Columns[k].Visible)
				{
					worksheet.Cells[4, ++num] = grid2.Columns[k].HeaderText;
				}
			}
			worksheet.get_Range((object)"A4", (object)"C4").Font.Bold = true;
			for (int l = 0; l < grid2.RowCount; l++)
			{
				num = 0;
				for (int m = 1; m < grid2.ColumnCount; m++)
				{
					if (grid2.Rows[l].Cells[m].Visible)
					{
						worksheet.Cells[l + 5, ++num] = grid2.Rows[l].Cells[m].Value;
					}
				}
			}
			worksheet.Cells.Select();
			worksheet.Cells.EntireColumn.AutoFit();
			((dynamic)worksheet.Cells[1, 1]).Select();
			application.Visible = true;
		}
		catch (Exception ex)
		{
			MessageBox.Show(string.Concat(string.Concat("Error: " + ex.Message, " Line: "), ex.Source), "Error");
		}
	}

	public static DataTable ToDataTable<T>(this IList<T> data)
	{
		PropertyDescriptorCollection properties = TypeDescriptor.GetProperties(typeof(T));
		DataTable dataTable = new DataTable();
		for (int i = 0; i < properties.Count; i++)
		{
			PropertyDescriptor propertyDescriptor = properties[i];
			dataTable.Columns.Add(propertyDescriptor.Name, propertyDescriptor.PropertyType);
		}
		object[] array = new object[properties.Count];
		foreach (T datum in data)
		{
			for (int j = 0; j < array.Length; j++)
			{
				array[j] = properties[j].GetValue(datum);
			}
			dataTable.Rows.Add(array);
		}
		return dataTable;
	}
}
