CC ?= cc
CFLAGS ?= -O2 -std=c99 -Wall -Wextra -pedantic

sbitgraft: sbitgraft.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f sbitgraft

.PHONY: clean
