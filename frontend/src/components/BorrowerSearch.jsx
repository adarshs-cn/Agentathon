import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Autocomplete, TextField, InputAdornment, Box, Stack, Typography } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import { api } from '../api/client';
import MonoId from './MonoId';
import { tokens } from '../theme/muiTheme';

// Jump to any borrower by account or customer number. Press "/" anywhere to focus it.
export default function BorrowerSearch({ width = 260 }) {
  const navigate = useNavigate();
  const [options, setOptions] = useState([]);
  const [text, setText] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || '').toLowerCase();
      if (e.key === '/' && tag !== 'input' && tag !== 'textarea') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (text.trim().length < 2) {
      setOptions([]);
      return undefined;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      api
        .accountsSearch(text.trim())
        .then((r) => !cancelled && setOptions(r.items || []))
        .catch(() => {});
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [text]);

  return (
    <Autocomplete
      size="small"
      options={options}
      filterOptions={(x) => x}
      inputValue={text}
      onInputChange={(_, v, reason) => reason !== 'reset' && setText(v)}
      onChange={(_, v) => {
        if (v) {
          navigate(`/trace?account=${v.account_id}`);
          setText('');
          setOptions([]);
        }
      }}
      getOptionLabel={(o) => o.account_id}
      noOptionsText={text.trim().length < 2 ? 'Type 2+ characters of an account or customer no' : 'No match'}
      renderOption={(props, o) => (
        <Box component="li" {...props} key={o.account_id}>
          <Stack sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={1} alignItems="baseline">
              <MonoId sx={{ fontSize: 12, fontWeight: 600, color: tokens.navbarBg }}>{o.account_id}</MonoId>
              <MonoId sx={{ fontSize: 11, color: tokens.statLabelGrey }}>{o.borrower_id}</MonoId>
            </Stack>
            <Typography sx={{ fontSize: 11, color: tokens.statLabelGrey }}>
              {o.name} · DPD {o.dpd} · {o.status}
            </Typography>
          </Stack>
        </Box>
      )}
      sx={{ width }}
      renderInput={(params) => (
        <TextField
          {...params}
          inputRef={inputRef}
          placeholder="Find a borrower  ( / )"
          InputProps={{
            ...params.InputProps,
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon sx={{ fontSize: 17, color: tokens.statLabelGrey }} />
              </InputAdornment>
            ),
            sx: { fontSize: 12, backgroundColor: tokens.containerBg, borderRadius: 2 },
          }}
        />
      )}
    />
  );
}
