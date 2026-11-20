import { Typography } from '@mui/material';
import { tokens } from '../theme/muiTheme';

export default function MonoId({ children, sx, ...rest }) {
  return (
    <Typography
      component="span"
      sx={{ fontFamily: tokens.fontMono, fontSize: '0.92em', ...sx }}
      {...rest}
    >
      {children}
    </Typography>
  );
}
