// lj92d in.jpg out.u16 : baseline lossless JPEG decoder (SOF3, predictor 1..7, Nf<=4, Huffman tables per comp)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { int minc[17], maxc[17], vp[17]; unsigned char val[256]; int ok; } huff;
static huff H[4];
static unsigned char *d; static long m, pos;
static int bit(void){ int b=(d[pos>>3]>>(7-(pos&7)))&1; pos++; return b; }
int main(int argc,char**argv){
  FILE*f=fopen(argv[1],"rb"); fseek(f,0,2); long n=ftell(f); fseek(f,0,0);
  unsigned char*b=malloc(n); fread(b,1,n,f); fclose(f);
  int P=0,Y=0,X=0,Nf=0,cid[4],ctab[4],pred=1,pt=0; long i=2, scan=0;
  while(i<n){
    if(b[i]!=0xff){fprintf(stderr,"bad marker at %ld\n",i);return 1;}
    int mk=b[i+1], L=(b[i+2]<<8)|b[i+3]; unsigned char*s=b+i+4;
    if(mk==0xc4){ int k=0; while(k<L-2){ int tc=s[k]&15; huff*h=&H[tc]; int cnt[16],tot=0,code=0,v=0;
        for(int l=0;l<16;l++){cnt[l]=s[k+1+l];tot+=cnt[l];}
        memcpy(h->val,s+k+17,tot);
        for(int l=1;l<=16;l++){h->vp[l]=v;h->minc[l]=code;code+=cnt[l-1];v+=cnt[l-1];h->maxc[l]=cnt[l-1]?code-1:-1;code<<=1;}
        h->ok=1; k+=17+tot; } }
    if(mk==0xc3){ P=s[0]; Y=(s[1]<<8)|s[2]; X=(s[3]<<8)|s[4]; Nf=s[5]; for(int c=0;c<Nf;c++) cid[c]=s[6+3*c]; }
    if(mk==0xda){ int Ns=s[0]; for(int c=0;c<Ns;c++) ctab[c]=s[2+2*c]>>4; pred=s[1+2*Ns]; pt=s[3+2*Ns]&15; scan=i+2+L; break; }
    i+=2+L;
  }
  fprintf(stderr,"P=%d Y=%d X=%d Nf=%d pred=%d pt=%d tabs=%d,%d scan@%ld\n",P,Y,X,Nf,pred,pt,ctab[0],ctab[1],scan);
  d=malloc(n); m=0; for(long j=scan;j<n;j++){ if(b[j]==0xff){ if(b[j+1]==0){d[m++]=0xff;j++;continue;} else break; } d[m++]=b[j]; }
  memset(d+m,0,8); pos=0;
  long W=(long)X*Nf; unsigned short*img=calloc(W*Y,2); long done=0;
  for(int y=0;y<Y;y++) for(int x=0;x<X;x++) for(int c=0;c<Nf;c++){
    huff*h=&H[ctab[c]]; int cd=0,s=-1;
    for(int l=1;l<=16;l++){ cd=(cd<<1)|bit(); if(h->maxc[l]>=0&&cd<=h->maxc[l]&&cd>=h->minc[l]){ s=h->val[h->vp[l]+cd-h->minc[l]]; break; } }
    if(s<0){ fprintf(stderr,"bad code y=%d x=%d c=%d\n",y,x,c); goto out; }
    int dv=0; if(s==16) dv=32768; else if(s){ int v=0; for(int k=0;k<s;k++) v=(v<<1)|bit(); dv= v>=(1<<(s-1))? v : v-(1<<s)+1; }
    long idx=(long)y*W+(long)x*Nf+c; int pv;
    if(y==0&&x==0) pv=1<<(P-pt-1);
    else if(y==0) pv=img[idx-Nf];
    else if(x==0) pv=img[idx-W];
    else { int Ra=img[idx-Nf],Rb=img[idx-W],Rc=img[idx-W-Nf];
      switch(pred){case 1:pv=Ra;break;case 2:pv=Rb;break;case 3:pv=Rc;break;case 4:pv=Ra+Rb-Rc;break;case 5:pv=Ra+((Rb-Rc)>>1);break;case 6:pv=Rb+((Ra-Rc)>>1);break;default:pv=(Ra+Rb)/2;} }
    img[idx]=(unsigned short)((pv+dv)&0xffff); done++;
  }
out:
  fprintf(stderr,"decoded %ld of %ld samples, bits %ld of %ld\n",done,W*Y,pos,m*8);
  if(pt) for(long j=0;j<W*Y;j++) img[j]=(unsigned short)(img[j]<<pt);   /* point transform: samples were coded >> pt */
  FILE*o=fopen(argv[2],"wb"); fwrite(img,2,W*Y,o); fclose(o); printf("%ld %d\n",W,Y); return 0; }
