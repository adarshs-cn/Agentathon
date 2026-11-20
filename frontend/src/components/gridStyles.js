import { tokens } from '../theme/muiTheme';

// The DataGrid look used on the Accounts page, shared so every table matches.
export const gridSx = {
  border: 'none',
  fontSize: 12.5,
  '& .MuiDataGrid-columnHeaders': {
    backgroundColor: tokens.cardGroupedBg,
    fontSize: 10.5,
    fontWeight: 700,
    color: tokens.statTitleGrey,
  },
  '& .MuiDataGrid-row': { cursor: 'pointer' },
  '& .MuiDataGrid-cell:focus, & .MuiDataGrid-cell:focus-within': { outline: 'none' },
};
