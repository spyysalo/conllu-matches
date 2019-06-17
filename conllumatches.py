#!/usr/bin/env python3

import sys
import os

from collections import Counter
from logging import warning, error


def argparser():
    from argparse import ArgumentParser
    ap = ArgumentParser()
    ap.add_argument('-d', '--no-duplicates', default=False, action='store_true',
                    help='don\'t output duplicated sentence texts')
    ap.add_argument('-l', '--min-length', default=None, type=int,
                    help='minimum sentence length to output (tokens)')
    ap.add_argument('file', nargs=2, help='CoNLL-U data')
    return ap


class FormatError(Exception):
    pass


class Word(object):
    def __init__(self, id_, form, lemma, upos, xpos, feats, head, deprel,
                 deps, misc):
        self.id = id_
        self.form = form
        self.lemma = lemma
        self.upos = upos
        self.xpos = xpos
        self.feats = feats
        self.head = head
        self.deprel = deprel
        self.deps = deps
        self.misc = misc

    def __str__(self):
        return '\t'.join([
            self.id, self.form, self.lemma, self.upos, self.xpos, self.feats,
            self.head, self.deprel, self.deps, self.misc
        ])


class Sentence(object):
    def __init__(self, comments, words, source, lineno, offset):
        self.comments = comments
        self.words = words
        self.source = source
        self.lineno = lineno
        self.offset = offset
        self._text = None

    def char_length(self):
        """Return total character length ignoring space"""
        return sum(not c.isspace() for w in self.words for c in w.form)

    def span(self):
        """Return (start, end) character span in source, ignoring space"""
        return self.offset, self.offset+self.char_length()

    def chars(self):
        """Return characters, ignoring space"""
        return ''.join([w.form for w in self.words])

    def text(self):
        if self._text is None:
            text_lines = [s for s in self.comments if s.startswith('# text = ')]
            if not text_lines:
                raise ValueError('no "# text" line: {} line {}'\
                                 .format(self.source, self.lineno))
            elif len(text_lines) > 1:
                raise ValueError('multiple "# text" lines: {} line {}'\
                                 .format(self.source, self.lineno))
            self._text = text_lines[0][len('# text = '):]
        return self._text

    def __str__(self):
        return '\n'.join(self.comments + [str(w) for w in self.words] + [''])
            
    

class Conllu(object):
    def __init__(self, path):
        self.path = path
        self.stream = open(path)
        self.lineno = 0
        self.offset = 0    # non-space offset
        self.finished = False
        self.current = self._get_sentence()

    def advance(self):
        s = self.current
        self.current = self._get_sentence()
        return s

    def _get_sentence(self):
        if self.finished:
            return None
        start_lineno = self.lineno + 1
        comments, words = [], []
        for l in self.stream:
            self.lineno += 1
            l = l.rstrip('\n')
            if not l or l.isspace():
                # blank line marks end of sentence
                if not words:
                    raise FormatError('empty sentence on line {} in {}'.format(
                        self.lineno, self.path))
                s = Sentence(comments, words, self.path, start_lineno,
                             self.offset)
                self.offset += s.char_length()
                return s
            elif l.startswith('#'):
                comments.append(l)
            else:
                fields = l.split('\t')
                if len(fields) != 10:
                    raise FormatError(
                        'expected 10 tab-separated fields, got {} on line {}'\
                        'in {}, got {}: {}'.format(
                            self.lineno, self.path, len(fields), l))
                words.append(Word(*fields))
        self.finished = True
        return None


def process_match(sentence1, sentence2, options, stats):
    s1_forms = [w.form for w in sentence1.words]
    s2_forms = [w.form for w in sentence2.words]
    if s1_forms != s2_forms:
        stats['tokenization mismatch'] += 1
        return False
    else:
        stats['tokenization match'] += 1

    s1_deps = [(w.head, w.deprel) for w in sentence1.words]
    s2_deps = [(w.head, w.deprel) for w in sentence2.words]
    if s1_deps != s2_deps:
        stats['head+deprel mismatch'] += 1
        return False
    else:
        stats['head+deprel match'] += 1

    if options.min_length is not None and len(s1_forms) < options.min_length:
        stats['under minimum length'] += 1
        return False

    if options.no_duplicates:
        text = sentence1.text()
        if text in process_match.seen:
            stats['duplicate'] += 1
            return False
        process_match.seen.add(text)
        
    # everything OK, output
    stats['all OK'] += 1
    print(sentence1)
    return True
process_match.seen = set()


def main(argv):
    args = argparser().parse_args(argv[1:])
    stats = Counter()
    n1, c1 = os.path.basename(args.file[0]), Conllu(args.file[0])
    n2, c2 = os.path.basename(args.file[1]), Conllu(args.file[1])
    while c1.current is not None and c2.current is not None:
        c1_start, c1_end = c1.current.span()
        c2_start, c2_end = c2.current.span()
        if ((c1_start, c1_end) != (c2_start, c2_end) and
            c1.current.chars() == c2.current.chars()):
            warning('possible desync: {}-{} != {}-{}:\n\t"{}" vs.\n\t"{}"'.format(
                c1_start, c1_end, c2_start, c2_end,
                ' '.join([w.form for w in c1.current.words]),
                ' '.join([w.form for w in c2.current.words])))
        if c1_start != c2_start and c1_end == c2_end:
            # Different start but both end on the same character, advance both
            stats['span mismatch ({})'.format(n1)] += 1
            stats['span mismatch ({})'.format(n2)] += 1
            c1.advance()
            c2.advance()
        elif c1_start < c2_start or c1_end < c2_end:
            stats['span mismatch ({})'.format(n1)] += 1
            c1.advance()
        elif c2_start < c1_start or c2_end < c1_end:
            stats['span mismatch ({})'.format(n2)] += 1
            c2.advance()
        else:
            assert c1_start == c2_start and c1_end == c2_end
            stats['span match ({})'.format(n1)] += 1
            stats['span match ({})'.format(n2)] += 1
            process_match(c1.current, c2.current, args, stats)
            c1.advance()
            c2.advance()

    for k, v in sorted(stats.items()):
        print('{}\t{}'.format(v, k), file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
